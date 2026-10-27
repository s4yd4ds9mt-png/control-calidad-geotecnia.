import streamlit as st
import pandas as pd
import numpy as np
import io
import math
import os
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ==============================================================================
# CONFIGURACIÓN TIPOGRÁFICA (REGISTRO CALIBRI REGULAR / BOLD CON FALLBACK)
# ==============================================================================

def registrar_fuentes():
    rutas_reg = [
        "/Library/Fonts/Microsoft/Calibri.ttf",
        "/Library/Fonts/Calibri.ttf",
        os.path.expanduser("~/Library/Fonts/Calibri.ttf"),
        "/System/Library/Fonts/Supplemental/Calibri.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf"
    ]
    rutas_bold = [
        "/Library/Fonts/Microsoft/Calibri Bold.ttf",
        "/Library/Fonts/Calibri Bold.ttf",
        os.path.expanduser("~/Library/Fonts/Calibri Bold.ttf"),
        "/System/Library/Fonts/Supplemental/Calibri Bold.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf"
    ]
    
    font_reg = None
    font_bold = None

    for r in rutas_reg:
        if os.path.exists(r):
            try:
                pdfmetrics.registerFont(TTFont("Calibri", r))
                font_reg = "Calibri"
                break
            except Exception:
                pass

    for r in rutas_bold:
        if os.path.exists(r):
            try:
                pdfmetrics.registerFont(TTFont("Calibri-Bold", r))
                font_bold = "Calibri-Bold"
                break
            except Exception:
                pass

    if font_reg and font_bold:
        return "Calibri", "Calibri-Bold"
    elif font_reg:
        return "Calibri", "Calibri"
    return "Helvetica", "Helvetica-Bold"

FUENTE_REGULAR, FUENTE_BOLD = registrar_fuentes()

# ==============================================================================
# 1. FUNCIONES GEOTÉCNICAS Y RECALCULOS
# ==============================================================================

def clasificar_sucs(pasa_200, pasa_4, ll, lp, ip):
    if ll is None or lp is None or ip <= 0:
        ip = 0.0
    if pasa_200 < 50:
        ret_4 = 100.0 - pasa_4
        es_grava = ret_4 > (100.0 - pasa_200) / 2.0
        if es_grava:
            if pasa_200 < 5: 
                return "GW / GP (Grava bien/mal graduada)"
            elif pasa_200 > 12:
                linea_a = 0.73 * (ll - 20)
                return "GM (Grava limosa)" if ip < 4 or ip < linea_a else "GC (Grava arcillosa)"
            else: 
                return "GW-GM / GP-GC (Grava con finos)"
        else:
            if pasa_200 < 5: 
                return "SW / SP (Arena bien/mal graduada)"
            elif pasa_200 > 12:
                linea_a = 0.73 * (ll - 20)
                return "SM (Arena limosa)" if ip < 4 or ip < linea_a else "SC (Arena arcillosa)"
            else: 
                return "SW-SM / SP-SC (Arena con finos)"
    else:
        linea_a = 0.73 * (ll - 20)
        if ll < 50:
            if ip > 7 and ip >= linea_a: 
                return "CL (Arcilla de baja plasticidad)"
            elif ip < 4 or ip < linea_a: 
                return "ML (Limo de baja plasticidad)"
            else: 
                return "CL-ML (Arcilla limosa)"
        else:
            if ip >= linea_a: 
                return "CH (Arcilla de alta plasticidad)"
            else: 
                return "MH (Limo de alta plasticidad)"

def calcular_granulometria_exacta(masas_g, masa_ini_g, masas_f, masa_ini_f, pct_lavado):
    mallas_g = ['3"', '2"', '1 1/2"', '1"', '3/4"', '3/8"', 'No.4']
    mallas_f = ['No.10', 'No.20', 'No.40', 'No.60', 'No.100', 'No.200', 'Pasa No.200']
    
    if masa_ini_g <= 0: masa_ini_g = 1.0
    if masa_ini_f <= 0: masa_ini_f = 1.0

    ret_parc_g = [(m / masa_ini_g) * 100.0 for m in masas_g]
    ret_acum_g = list(np.cumsum(ret_parc_g))
    pasa_g = [max(0.0, 100.0 - r) for r in ret_acum_g]
    pasa_no4 = pasa_g[-1] if len(pasa_g) > 0 else 50.0

    ret_parc_f_local = [(m / masa_ini_f) * 100.0 for m in masas_f]
    ret_acum_f_local = list(np.cumsum(ret_parc_f_local))
    
    pasa_f = [max(0.0, pasa_no4 - (r_loc / 100.0) * pasa_no4) for r_loc in ret_acum_f_local]
    if len(pasa_f) > 0:
        pasa_f[-1] = max(0.0, pasa_f[-1] - pct_lavado)

    all_mallas = mallas_g + mallas_f
    pasa_combinado = pasa_g + pasa_f
    
    pasa_limpio = []
    min_val = 100.0
    for p in pasa_combinado:
        val = min(min_val, max(0.0, p))
        pasa_limpio.append(val)
        min_val = val

    ret_acum_global = [max(0.0, 100.0 - p) for p in pasa_limpio]
    ret_parc_global = []
    prev = 0.0
    for r in ret_acum_global:
        ret_parc_global.append(max(0.0, r - prev))
        prev = r

    all_masas = [round(float(m), 1) for m in masas_g] + [round(float(m), 1) for m in masas_f]

    df_res = pd.DataFrame({
        'Malla': all_mallas,
        'Fracción': ['Gruesa']*len(mallas_g) + ['Fina']*len(mallas_f),
        'Masa Retenida (g)': np.round(all_masas, 1),
        '% Retenido Parcial': np.round(ret_parc_global, 1),
        '% Retenido Acumulado': np.round(ret_acum_global, 1),
        '% Que Pasa': np.round(pasa_limpio, 1)
    })

    masa_lavado_g = round((pct_lavado / 100.0) * masa_ini_f, 1)
    return df_res, masa_lavado_g

def obtener_pasa_referencia(banco_props):
    pasa_g_ref = banco_props.get("pasa_g_ref", [100.0, 100.0, 95.0, 85.0, 70.0, 55.0, 42.0])
    pasa_f_ref = banco_props.get("pasa_f_ref", [30.0, 22.0, 16.0, 12.0, 8.0, 5.0, 3.0])
    return pasa_g_ref, pasa_f_ref

def convertir_curvas_a_masas(pasa_g, masa_ini_g, pasa_f, masa_ini_f):
    ret_g_masas = []
    prev_g = 100.0
    for p in pasa_g:
        diff_pct = max(0.0, prev_g - p)
        ret_g_masas.append(round((diff_pct / 100.0) * masa_ini_g, 1))
        prev_g = p

    pasa_no4 = pasa_g[-1] if len(pasa_g) > 0 else 50.0
    ret_f_masas = []
    prev_f = pasa_no4
    for p in pasa_f:
        diff_pct = max(0.0, prev_f - p)
        fraccion = (diff_pct / pasa_no4) if pasa_no4 > 0 else 0.0
        ret_f_masas.append(round(fraccion * masa_ini_f, 1))
        prev_f = p

    return ret_g_masas, ret_f_masas

def simular_limites_crudos(ll_objetivo, lp_objetivo):
    tara_ll = f"C-{np.random.randint(1, 50):02d}"
    m_tara_ll = round(float(np.random.uniform(18.0, 24.0)), 2)
    ws_ll = round(float(np.random.uniform(18.0, 22.0)), 2)
    ww_ll = round(ws_ll * (ll_objetivo / 100.0), 2)
    m_seco_ll = round(m_tara_ll + ws_ll, 2)
    m_humedo_ll = round(m_seco_ll + ww_ll, 2)
    ll_calc = round(((m_humedo_ll - m_seco_ll) / (m_seco_ll - m_tara_ll)) * 100.0, 1)

    tara_lp = f"R-{np.random.randint(1, 50):02d}"
    m_tara_lp = round(float(np.random.uniform(14.0, 19.0)), 2)
    ws_lp = round(float(np.random.uniform(8.0, 12.0)), 2)
    ww_lp = round(ws_lp * (lp_objetivo / 100.0), 2)
    m_seco_lp = round(m_tara_lp + ws_lp, 2)
    m_humedo_lp = round(m_seco_lp + ww_lp, 2)
    lp_calc = round(((m_humedo_lp - m_seco_lp) / (m_seco_lp - m_tara_lp)) * 100.0, 1)
    ip_calc = round(max(0.0, ll_calc - lp_calc), 1)

    df_limites = pd.DataFrame([
        {
            "Determinación": "Límite Líquido (LL)",
            "Golpes": 25,
            "No. Tara": tara_ll,
            "Masa Tara (g)": m_tara_ll,
            "Tara + Húmedo (g)": m_humedo_ll,
            "Tara + Seco (g)": m_seco_ll,
            "Agua (g)": round(m_humedo_ll - m_seco_ll, 2),
            "Suelo Seco (g)": round(m_seco_ll - m_tara_ll, 2),
            "% Humedad": ll_calc
        },
        {
            "Determinación": "Límite Plástico (LP)",
            "Golpes": "-",
            "No. Tara": tara_lp,
            "Masa Tara (g)": m_tara_lp,
            "Tara + Húmedo (g)": m_humedo_lp,
            "Tara + Seco (g)": m_seco_lp,
            "Agua (g)": round(m_humedo_ll - m_seco_ll, 2),
            "Suelo Seco (g)": round(m_seco_lp - m_tara_lp, 2),
            "% Humedad": lp_calc
        }
    ])

    return df_limites, ll_calc, lp_calc, ip_calc

def simular_mvs_suelta(mv_suelta_target, cfg_recipiente):
    vol_recipiente_cm3 = float(cfg_recipiente.get("volumen", 10000.0))
    peso_recipiente_g = float(cfg_recipiente.get("peso", 5250.0))
    recipiente_id = cfg_recipiente.get("id", "REC-10L")
    
    gamma_s = round(float(mv_suelta_target), 3)
    peso_suelo_seco_g = round(gamma_s * vol_recipiente_cm3, 1)
    peso_total_rec_suelo_g = round(peso_recipiente_g + peso_suelo_seco_g, 1)
    
    datos_suelta = {
        "Recipiente_ID": recipiente_id,
        "Volumen_Recipiente_cm3": vol_recipiente_cm3,
        "Peso_Recipiente_g": peso_recipiente_g,
        "Peso_Total_Rec_Suelo_g": peso_total_rec_suelo_g,
        "Peso_Suelo_Seco_g": peso_suelo_seco_g,
        "MVS_Suelta": gamma_s
    }
    return datos_suelta

def simular_proctor_4puntos(mvsm_target, w_opt_target, ret_no4_pct, catalogo_moldes):
    tipo_molde = "Grande (6\")" if ret_no4_pct >= 20.0 else "Chico (4\")"
    molde_info = catalogo_moldes[tipo_molde]
    
    vol_molde = round(float(molde_info["volumen"]), 1)
    peso_molde = round(float(molde_info["peso"]), 1)
    molde_id = molde_info["id"]

    desfases_w = [-3.2, -1.6, -0.2, +1.8]
    k_curvatura = 0.0045

    filas_proctor = []
    for i, dw in enumerate(desfases_w, start=1):
        w_i = round(max(1.0, w_opt_target + dw + np.random.normal(0, 0.06)), 1)
        delta = w_i - w_opt_target
        gamma_d_i = round(mvsm_target - (k_curvatura * (delta ** 2)), 3)
        gamma_h_i = round(gamma_d_i * (1.0 + (w_i / 100.0)), 3)
        
        m_suelo_humedo = round(gamma_h_i * vol_molde, 1)
        m_molde_suelo = round(peso_molde + m_suelo_humedo, 1)
        
        tara_punto_id = f"CH-{np.random.randint(10, 99)}"
        m_tara_w = round(float(np.random.uniform(80.0, 120.0)), 1)
        ws_w = round(float(np.random.uniform(150.0, 220.0)), 1)
        ww_w = round(ws_w * (w_i / 100.0), 1)
        m_seco_tara = round(m_tara_w + ws_w, 1)
        m_humedo_tara = round(m_seco_tara + ww_w, 1)
        w_verif = round(((m_humedo_tara - m_seco_tara) / (m_seco_tara - m_tara_w)) * 100.0, 1)

        filas_proctor.append({
            "Punto": f"Punto {i}" + (" (Bajada)" if i == 4 else " (Subida)"),
            "Molde ID": molde_id,
            "Volumen (cm³)": vol_molde,
            "Molde + Suelo (g)": m_molde_suelo,
            "Peso Molde (g)": peso_molde,
            "Suelo Húmedo (g)": m_suelo_humedo,
            "M.V. Húmeda (g/cm³)": gamma_h_i,
            "No. Tara": tara_punto_id,
            "M. Tara (g)": m_tara_w,
            "Tara + Húm (g)": m_humedo_tara,
            "Tara + Seco (g)": m_seco_tara,
            "Agua (g)": round(m_humedo_tara - m_seco_tara, 1),
            "Suelo Seco (g)": round(m_seco_tara - m_tara_w, 1),
            "Humedad (%)": w_verif,
            "M.V. Seca (g/cm³)": gamma_d_i
        })

    df_proctor = pd.DataFrame(filas_proctor)
    return df_proctor, tipo_molde, molde_id, vol_molde

def simular_cbr_expansion(cbr_target, exp_target, mvsm_ref, w_opt_ref, grado_comp_pct, molde_cbr_info):
    diametro = float(molde_cbr_info.get("diametro_cm", 15.24))
    h_molde = float(molde_cbr_info.get("altura_molde_cm", 17.78))
    h_disco = float(molde_cbr_info.get("altura_disco_cm", 6.14))
    peso_molde = float(molde_cbr_info.get("peso", 5820.0))
    molde_id = molde_cbr_info.get("id", "CBR-01")

    h_suelo = round(h_molde - h_disco, 2)
    area = round((math.pi * (diametro ** 2)) / 4.0, 2)
    vol_esp = round(area * h_suelo, 1)

    delta_w = round(float(np.random.uniform(-0.45, 0.45)), 1)
    w_ini = round(w_opt_ref + delta_w, 1)

    tara_cbr_id = f"TC-{np.random.randint(10, 99)}"
    m_tara_cbr = round(float(np.random.uniform(80.0, 120.0)), 1)
    ws_cbr = round(float(np.random.uniform(160.0, 220.0)), 1)
    ww_cbr = round(ws_cbr * (w_ini / 100.0), 1)
    m_seco_tara_cbr = round(m_tara_cbr + ws_cbr, 1)
    m_humedo_tara_cbr = round(m_seco_tara_cbr + ww_cbr, 1)
    m_agua_cbr = round(m_humedo_tara_cbr - m_seco_tara_cbr, 1)
    m_suelo_seco_cbr = round(m_seco_tara_cbr - m_tara_cbr, 1)
    w_ini_calc = round((m_agua_cbr / m_suelo_seco_cbr) * 100.0, 1)

    disp_gc = float(np.random.uniform(-1.5, 1.5))
    gc_real = round(grado_comp_pct + disp_gc, 1)
    mvs_esp = round(mvsm_ref * (gc_real / 100.0), 3)

    mvh_esp = round(mvs_esp * (1.0 + (w_ini_calc / 100.0)), 3)
    m_suelo_hum = round(mvh_esp * vol_esp, 1)
    m_molde_suelo_cbr = round(peso_molde + m_suelo_hum, 1)

    delta_l_cm = (exp_target / 100.0) * h_suelo
    delta_l_mm = round(delta_l_cm * 10.0, 2)
    l_ini_mm = round(float(np.random.uniform(1.00, 2.50)), 2)
    l_fin_mm = round(l_ini_mm + delta_l_mm, 2)
    exp_calc = round(((l_fin_mm - l_ini_mm) / (h_suelo * 10.0)) * 100.0, 2)

    penetraciones_pulg = [0.025, 0.050, 0.075, 0.100, 0.125, 0.150, 0.175, 0.200, 0.300, 0.400, 0.500]
    carga_01_kgf = round((cbr_target / 100.0) * 1358.0, 1)
    cbr_01_calc = round((carga_01_kgf / 1358.0) * 100.0, 1)

    ratio_02 = float(np.random.uniform(1.22, 1.30))
    carga_02_kgf = round(carga_01_kgf * ratio_02, 1)
    cbr_02_calc = round((carga_02_kgf / 2037.0) * 100.0, 1)

    cargas_kgf = []
    for p in penetraciones_pulg:
        if p <= 0.100:
            factor_p = (p / 0.100) ** 0.85
            c_val = round(carga_01_kgf * factor_p, 1)
        elif p <= 0.200:
            t = (p - 0.100) / 0.100
            c_val = round(carga_01_kgf + (carga_02_kgf - carga_01_kgf) * t, 1)
        else:
            extra = (p - 0.200) * (carga_02_kgf * 0.45)
            c_val = round(carga_02_kgf + extra, 1)
        cargas_kgf.append(c_val)

    df_penetracion = pd.DataFrame({
        "Penetración (pulg)": [f"{p:.3f}\"" for p in penetraciones_pulg],
        "Penetración (mm)": [round(p * 25.4, 2) for p in penetraciones_pulg],
        "Carga (kgf)": cargas_kgf
    })

    datos_especimen = {
        "Molde_ID": molde_id,
        "Diametro_cm": diametro,
        "Area_cm2": area,
        "Altura_Molde_cm": h_molde,
        "Altura_Disco_cm": h_disco,
        "Altura_Suelo_cm": h_suelo,
        "Volumen_cm3": vol_esp,
        "Peso_Molde_g": peso_molde,
        "Molde_Suelo_g": m_molde_suelo_cbr,
        "Suelo_Humedo_g": m_suelo_hum,
        "MV_Humeda": mvh_esp,
        "MV_Seca": mvs_esp,
        "Grado_Comp_Real": gc_real,
        "No_Tara": tara_cbr_id,
        "M_Tara_g": m_tara_cbr,
        "Tara_Hum_g": m_humedo_tara_cbr,
        "Tara_Sec_g": m_seco_tara_cbr,
        "Agua_g": m_agua_cbr,
        "Suelo_Seco_g": m_suelo_seco_cbr,
        "W_Ini": w_ini_calc,
        "L_Ini_mm": l_ini_mm,
        "L_Fin_mm": l_fin_mm,
        "Delta_L_mm": delta_l_mm,
        "Exp_Calc": exp_calc,
        "Carga_01_kgf": carga_01_kgf,
        "CBR_01": cbr_01_calc,
        "Carga_02_kgf": carga_02_kgf,
        "CBR_02": cbr_02_calc,
        "CBR_Final": cbr_01_calc
    }

    return df_penetracion, datos_especimen

def recalcular_muestras_existentes(muestras_previas, b_props, grado_comp):
    pasa_g_ref, pasa_f_ref = obtener_pasa_referencia(b_props)
    lav_ref = b_props.get("pct_lav", 4.5)
    muestras_actualizadas = []

    if 'in_suelta_peso' in st.session_state and 'in_suelta_vol' in st.session_state:
        st.session_state['molde_suelta_config']['peso'] = float(st.session_state['in_suelta_peso'])
        st.session_state['molde_suelta_config']['volumen'] = float(st.session_state['in_suelta_vol'])

    cfg_suelta_activa = st.session_state['molde_suelta_config']

    for m in muestras_previas:
        mg_muestra = round(float(m.get('Masa_Gruesa', np.random.uniform(17000.0, 19000.0))), 1)
        mf_muestra = round(float(m.get('Masa_Fina', np.random.uniform(300.0, 400.0))), 1)

        sesgo = float(np.random.normal(0, 0.6))

        pasa_g_var = []
        prev = 100.0
        for p_ref in pasa_g_ref:
            val = round(max(0.0, min(prev, p_ref + sesgo + np.random.normal(0, 0.3))), 1)
            pasa_g_var.append(val)
            prev = val

        pasa_f_var = []
        prev = pasa_g_var[-1]
        for p_ref in pasa_f_ref:
            val = round(max(0.0, min(prev, p_ref + sesgo + np.random.normal(0, 0.3))), 1)
            pasa_f_var.append(val)
            prev = val

        mg_sint, mf_sint = convertir_curvas_a_masas(pasa_g_var, mg_muestra, pasa_f_var, mf_muestra)
        lav_sint = round(max(0.5, lav_ref + float(np.random.normal(0, 0.2))), 1)

        df_gran_s, masa_lavado_g = calcular_granulometria_exacta(
            mg_sint, mg_muestra, mf_sint, mf_muestra, lav_sint
        )

        pasa_4 = df_gran_s.loc[df_gran_s['Malla'] == 'No.4', '% Que Pasa'].values[0] if 'No.4' in df_gran_s['Malla'].values else 50.0
        ret_no4 = 100.0 - pasa_4

        factor = float(np.random.normal(0, 1.0))
        ll_target = max(15.0, b_props["ll"] + factor * 1.2)
        lp_target = max(10.0, b_props["lp"] + factor * 0.6)
        df_limites_s, ll_calc, lp_calc, ip_calc = simular_limites_crudos(ll_target, lp_target)

        mvsm_target = round(max(1.500, float(b_props["mv_max"]) + np.random.normal(0, 0.015)), 3)
        w_opt_target = round(max(4.0, float(b_props["w_opt"]) + np.random.normal(0, 0.25)), 1)
        
        df_proctor_s, tipo_molde, molde_id, vol_molde = simular_proctor_4puntos(
            mvsm_target, w_opt_target, ret_no4, st.session_state['catalogo_moldes']
        )

        cbr_target = round(max(5.0, b_props["cbr"] - factor * 2.0), 1)
        exp_target = round(max(0.05, b_props["exp"] + factor * 0.03), 2)
        
        df_pen_s, cbr_esp_s = simular_cbr_expansion(
            cbr_target, exp_target, mvsm_target, w_opt_target, 
            grado_comp, st.session_state['molde_cbr_config']
        )

        mv_suelta_target = round(max(1.000, float(b_props["mv_suelta"]) - factor * 0.01), 3)
        datos_suelta_s = simular_mvs_suelta(mv_suelta_target, cfg_suelta_activa)

        pasa_200 = df_gran_s.loc[df_gran_s['Malla'] == 'No.200', '% Que Pasa'].values[0] if 'No.200' in df_gran_s['Malla'].values else 0.0
        sucs_s = clasificar_sucs(pasa_200, pasa_4, ll_calc, lp_calc, ip_calc)

        cfg_campo = st.session_state.get('datos_campo_persistentes', {})

        muestras_actualizadas.append({
            'ID': m['ID'],
            'Cliente': m['Cliente'],
            'Contratista': m['Contratista'],
            'Banco': m['Banco'],
            'Calidad': m['Calidad'],
            'Localizacion': m['Localizacion'],
            'Tramo': m['Tramo'],
            'F_Recepcion': m['F_Recepcion'],
            'F_Ensaye': m['F_Ensaye'],
            'F_Informe': m['F_Informe'],
            'Muestra_Tomada_En': cfg_campo.get('tomada_en', m.get('Muestra_Tomada_En', 'Banco de Préstamo')),
            'Procedencia': cfg_campo.get('procedencia', m.get('Procedencia', m['Banco'])),
            'Para_Utilizarse_En': cfg_campo.get('para_utilizarse', m.get('Para_Utilizarse_En', f"Capa de {m['Calidad']}")),
            'Observaciones': cfg_campo.get('observaciones', m.get('Observaciones', 'El material cumple con las normas SCT aplicables al proyecto.')),
            'df_gran': df_gran_s,
            'df_limites': df_limites_s,
            'df_proctor': df_proctor_s,
            'df_penetracion': df_pen_s,
            'cbr_esp': cbr_esp_s,
            'datos_suelta': datos_suelta_s,
            'Tipo_Molde': tipo_molde,
            'Molde_ID': molde_id,
            'Vol_Molde': vol_molde,
            'Masa_Gruesa': mg_muestra,
            'Masa_Fina': mf_muestra,
            'Pct_Lavado': lav_sint,
            'Masa_Lavado_g': masa_lavado_g,
            'masas_g': mg_sint,
            'masas_f': mf_sint,
            'LL': ll_calc, 'LP': lp_calc, 'IP': ip_calc,
            'MV_Suelta': datos_suelta_s['MVS_Suelta'], 'MV_Max': mvsm_target, 'W_Opt': w_opt_target,
            'CBR': cbr_esp_s['CBR_Final'], 'Expansion': cbr_esp_s['Exp_Calc'], 'SUCS': sucs_s
        })
    return muestras_actualizadas

def generar_muestras_logic(f_ini, f_fin, n_muestras, consecutivo_ini, cliente, contratista, t_nombre, t_info, b_nombre, c_nombre, b_props, grado_comp):
    pasa_g_ref, pasa_f_ref = obtener_pasa_referencia(b_props)
    lav_ref = b_props.get("pct_lav", 4.5)

    muestras_temporales = []
    dias_totales_rango = (f_fin - f_ini).days

    cfg_campo = st.session_state.get('datos_campo_persistentes', {})

    for i in range(n_muestras):
        dias_aleatorios = np.random.randint(0, max(1, dias_totales_rango + 1))
        f_recepcion = f_ini + timedelta(days=int(dias_aleatorios))

        dias_desfas_ensaye = np.random.randint(7, 16)
        f_ensaye = f_recepcion + timedelta(days=int(dias_desfas_ensaye))
        f_informe = f_ensaye + timedelta(days=1)

        mg_muestra = round(float(np.random.uniform(17000.0, 19000.0)), 1)
        mf_muestra = round(float(np.random.uniform(300.0, 400.0)), 1)

        sesgo = float(np.random.normal(0, 0.6))

        pasa_g_var = []
        prev = 100.0
        for p_ref in pasa_g_ref:
            val = round(max(0.0, min(prev, p_ref + sesgo + np.random.normal(0, 0.3))), 1)
            pasa_g_var.append(val)
            prev = val

        pasa_f_var = []
        prev = pasa_g_var[-1]
        for p_ref in pasa_f_ref:
            val = round(max(0.0, min(prev, p_ref + sesgo + np.random.normal(0, 0.3))), 1)
            pasa_f_var.append(val)
            prev = val

        mg_sint, mf_sint = convertir_curvas_a_masas(pasa_g_var, mg_muestra, pasa_f_var, mf_muestra)
        lav_sint = round(max(0.5, lav_ref + float(np.random.normal(0, 0.2))), 1)

        loc_str = f"Km. {np.random.randint(10, 120)}+{np.random.randint(0, 999):03d}"
        muestras_temporales.append({
            'f_rec_obj': f_recepcion,
            'F_Recepcion': f_recepcion.strftime("%d/%m/%Y"),
            'F_Ensaye': f_ensaye.strftime("%d/%m/%Y"),
            'F_Informe': f_informe.strftime("%d/%m/%Y"),
            'Cliente': cliente,
            'Contratista': contratista,
            'Banco': b_nombre,
            'Calidad': c_nombre,
            'Localizacion': loc_str,
            'Tramo': t_nombre,
            'prefijo_tramo': t_info['codigo'],
            'Muestra_Tomada_En': cfg_campo.get('tomada_en', 'Banco de Préstamo'),
            'Procedencia': cfg_campo.get('procedencia', b_nombre),
            'Para_Utilizarse_En': cfg_campo.get('para_utilizarse', f"Capa de {c_nombre}"),
            'Observaciones': cfg_campo.get('observaciones', 'El material analizado cumple satisfactoriamente con la normatividad del proyecto.'),
            'mg_muestra': mg_muestra,
            'mf_muestra': mf_muestra,
            'masas_g': mg_sint,
            'masas_f': mf_sint,
            'lav': lav_sint
        })

    muestras_temporales = sorted(muestras_temporales, key=lambda x: x['f_rec_obj'])

    muestras_finales = []
    for idx, m in enumerate(muestras_temporales, start=consecutivo_ini):
        fecha_str = m['F_Recepcion']
        pref_tramo = m['prefijo_tramo']
        id_muestra = f"MAT-{fecha_str}-{pref_tramo}-GE-{idx:04d}"

        df_gran_s, masa_lavado_g = calcular_granulometria_exacta(
            m['masas_g'], m['mg_muestra'], m['masas_f'], m['mf_muestra'], m['lav']
        )

        pasa_4 = df_gran_s.loc[df_gran_s['Malla'] == 'No.4', '% Que Pasa'].values[0] if 'No.4' in df_gran_s['Malla'].values else 50.0
        ret_no4 = 100.0 - pasa_4

        factor = float(np.random.normal(0, 1.0))
        ll_target = max(15.0, b_props["ll"] + factor * 1.2)
        lp_target = max(10.0, b_props["lp"] + factor * 0.6)
        df_limites_s, ll_calc, lp_calc, ip_calc = simular_limites_crudos(ll_target, lp_target)

        mvsm_target = round(max(1.500, float(b_props["mv_max"]) + np.random.normal(0, 0.015)), 3)
        w_opt_target = round(max(4.0, float(b_props["w_opt"]) + np.random.normal(0, 0.25)), 1)
        
        df_proctor_s, tipo_molde, molde_id, vol_molde = simular_proctor_4puntos(
            mvsm_target, w_opt_target, ret_no4, st.session_state['catalogo_moldes']
        )

        cbr_target = round(max(5.0, b_props["cbr"] - factor * 2.0), 1)
        exp_target = round(max(0.05, b_props["exp"] + factor * 0.03), 2)
        
        df_pen_s, cbr_esp_s = simular_cbr_expansion(
            cbr_target, exp_target, mvsm_target, w_opt_target, 
            grado_comp, st.session_state['molde_cbr_config']
        )

        mv_suelta_target = round(max(1.000, float(b_props["mv_suelta"]) - factor * 0.01), 3)
        datos_suelta_s = simular_mvs_suelta(mv_suelta_target, st.session_state['molde_suelta_config'])

        pasa_200 = df_gran_s.loc[df_gran_s['Malla'] == 'No.200', '% Que Pasa'].values[0] if 'No.200' in df_gran_s['Malla'].values else 0.0
        sucs_s = clasificar_sucs(pasa_200, pasa_4, ll_calc, lp_calc, ip_calc)

        muestras_finales.append({
            'ID': id_muestra,
            'Cliente': m['Cliente'],
            'Contratista': m['Contratista'],
            'Banco': m['Banco'],
            'Calidad': m['Calidad'],
            'Localizacion': m['Localizacion'],
            'Tramo': m['Tramo'],
            'F_Recepcion': m['F_Recepcion'],
            'F_Ensaye': m['F_Ensaye'],
            'F_Informe': m['F_Informe'],
            'Muestra_Tomada_En': m['Muestra_Tomada_En'],
            'Procedencia': m['Procedencia'],
            'Para_Utilizarse_En': m['Para_Utilizarse_En'],
            'Observaciones': m['Observaciones'],
            'df_gran': df_gran_s,
            'df_limites': df_limites_s,
            'df_proctor': df_proctor_s,
            'df_penetracion': df_pen_s,
            'cbr_esp': cbr_esp_s,
            'datos_suelta': datos_suelta_s,
            'Tipo_Molde': tipo_molde,
            'Molde_ID': molde_id,
            'Vol_Molde': vol_molde,
            'Masa_Gruesa': m['mg_muestra'],
            'Masa_Fina': mf_muestra,
            'Pct_Lavado': lav_sint,
            'Masa_Lavado_g': masa_lavado_g,
            'masas_g': mg_sint,
            'masas_f': mf_sint,
            'LL': ll_calc, 'LP': lp_calc, 'IP': ip_calc,
            'MV_Suelta': datos_suelta_s['MVS_Suelta'], 'MV_Max': mvsm_target, 'W_Opt': w_opt_target,
            'CBR': cbr_esp_s['CBR_Final'], 'Expansion': cbr_esp_s['Exp_Calc'], 'SUCS': sucs_s
        })
    return muestras_finales

# ==============================================================================
# 2. GENERADORES DE INFORMES PDF (CANVAS DIRECTO Y PLANTILLA)
# ==============================================================================

def generar_pdf_lote_resumen(muestras, obra_nombre, banco_nombre, calidad_nombre):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(letter))
    ancho, alto = landscape(letter) # 792 x 612 pt

    cols_x = [25, 140, 195, 290, 330, 370, 425, 475, 520, 575, 620, 665]
    cols_anchos = [115, 55, 95, 40, 40, 55, 50, 45, 55, 45, 45, 102]
    total_ancho = ancho - 50 # 742 pt

    def dibujar_encabezados(num_pagina):
        c.setFont(FUENTE_BOLD, 11)
        c.setFillColor(colors.HexColor('#1A365D'))
        c.drawCentredString(ancho / 2.0, 580, "REPORTE CONSOLIDADO DE BITÁCORA - CONTROL DE CALIDAD")

        c.setFont(FUENTE_REGULAR, 8)
        c.setFillColor(colors.HexColor('#4A5568'))
        c.drawCentredString(ancho / 2.0, 566, f"Obra: {obra_nombre[:60]} | Banco: {banco_nombre} | Calidad: {calidad_nombre}")

        c.setStrokeColor(colors.HexColor('#1A365D'))
        c.setLineWidth(1)
        c.line(25, 556, ancho - 25, 556)

        c.setFillColor(colors.HexColor('#2B6CB0'))
        c.rect(25, 536, total_ancho, 18, fill=1, stroke=0)

        c.setFont(FUENTE_BOLD, 6.5)
        c.setFillColor(colors.white)
        titulos = ["No. Muestra", "F. Recep.", "Tramo", "LL (%)", "IP (%)", "MVS Suelta", "MVSM", "W Ópt", "Grado Comp", "CBR (%)", "Exp (%)", "SUCS"]
        
        c.drawString(cols_x[0] + 3, 542, titulos[0])
        c.drawCentredString(cols_x[1] + cols_anchos[1]/2, 542, titulos[1])
        c.drawString(cols_x[2] + 3, 542, titulos[2])
        for i in range(3, 11):
            c.drawCentredString(cols_x[i] + cols_anchos[i]/2, 542, titulos[i])
        c.drawString(cols_x[11] + 3, 542, titulos[11])

    pag = 1
    dibujar_encabezados(pag)
    y = 518
    fila_alto = 16

    for idx_row, m in enumerate(muestras):
        if y < 45:
            c.setFont(FUENTE_REGULAR, 6.5)
            c.setFillColor(colors.HexColor('#718096'))
            c.drawString(25, 30, f"Página {pag}")
            c.showPage()
            pag += 1
            dibujar_encabezados(pag)
            y = 518

        c.setFillColor(colors.white if idx_row % 2 == 0 else colors.HexColor('#F7FAFC'))
        c.rect(25, y, total_ancho, fila_alto, fill=1, stroke=0)

        c.setStrokeColor(colors.HexColor('#E2E8F0'))
        c.setLineWidth(0.5)
        c.line(25, y, 25 + total_ancho, y)

        cbr_d = m.get('cbr_esp', {})
        try:
            gc_val = float(cbr_d.get('Grado_Comp_Real', 100.0))
            cbr_val = float(cbr_d.get('CBR_Final', m.get('CBR', 80.0)))
            exp_val = float(cbr_d.get('Exp_Calc', m.get('Expansion', 0.10)))
            ll_v = float(m.get('LL', 0.0))
            ip_v = float(m.get('IP', 0.0))
            mvs_v = float(m.get('MV_Suelta', 1.500))
            
            df_proc = m.get('df_proctor', pd.DataFrame())
            if 'MV_Max' in m and m['MV_Max'] is not None:
                mvsm_v = float(m['MV_Max'])
            elif 'M.V. Seca (g/cm³)' in df_proc.columns and len(df_proc) > 0:
                mvsm_v = float(df_proc['M.V. Seca (g/cm³)'].max())
            else:
                mvsm_v = 2.050

            wopt_v = float(m.get('W_Opt', 8.5))
        except (ValueError, TypeError):
            gc_val, cbr_val, exp_val, ll_v, ip_v, mvs_v, mvsm_v, wopt_v = 100.0, 80.0, 0.10, 0.0, 0.0, 1.500, 2.050, 8.5

        c.setFont(FUENTE_REGULAR, 6.5)
        c.setFillColor(colors.HexColor('#262626'))

        c.drawString(cols_x[0] + 3, y + 4.5, str(m.get('ID', '-')))
        c.drawCentredString(cols_x[1] + cols_anchos[1]/2, y + 4.5, str(m.get('F_Recepcion', '-')))
        c.drawString(cols_x[2] + 3, y + 4.5, str(m.get('Tramo', '-'))[:22])
        c.drawCentredString(cols_x[3] + cols_anchos[3]/2, y + 4.5, f"{ll_v:.1f}")
        c.drawCentredString(cols_x[4] + cols_anchos[4]/2, y + 4.5, f"{ip_v:.1f}")
        c.drawCentredString(cols_x[5] + cols_anchos[5]/2, y + 4.5, f"{mvs_v:.3f}")
        c.drawCentredString(cols_x[6] + cols_anchos[6]/2, y + 4.5, f"{mvsm_v:.3f}")
        c.drawCentredString(cols_x[7] + cols_anchos[7]/2, y + 4.5, f"{wopt_v:.1f}")
        c.drawCentredString(cols_x[8] + cols_anchos[8]/2, y + 4.5, f"{gc_val:.1f}%")
        c.drawCentredString(cols_x[9] + cols_anchos[9]/2, y + 4.5, f"{cbr_val:.1f}")
        c.drawCentredString(cols_x[10] + cols_anchos[10]/2, y + 4.5, f"{exp_val:.2f}")
        c.drawString(cols_x[11] + 3, y + 4.5, str(m.get('SUCS', '-'))[:25])

        y -= fila_alto

    c.setFont(FUENTE_REGULAR, 6.5)
    c.setFillColor(colors.HexColor('#718096'))
    c.drawString(25, 30, f"Página {pag} - Fin del Reporte")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_informe(m, obra_nombre):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=25, leftMargin=25, topMargin=25, bottomMargin=25)
    story = []
    styles = getSampleStyleSheet()

    titulo_style = ParagraphStyle('TituloDoc', parent=styles['Heading1'], fontName=FUENTE_BOLD, fontSize=10.5, textColor=colors.HexColor('#1A365D'), alignment=1)
    subtitulo_style = ParagraphStyle('SubTituloDoc', parent=styles['Normal'], fontName=FUENTE_REGULAR, fontSize=7.5, textColor=colors.HexColor('#4A5568'), alignment=1)
    seccion_style = ParagraphStyle('SeccionHeader', parent=styles['Heading2'], fontName=FUENTE_BOLD, fontSize=8, textColor=colors.HexColor('#2B6CB0'), spaceBefore=3, spaceAfter=2)
    celda_head = ParagraphStyle('TH', fontName=FUENTE_BOLD, fontSize=6, textColor=colors.white, alignment=1)
    celda_body = ParagraphStyle('TD', fontName=FUENTE_REGULAR, fontSize=6, alignment=1)

    story.append(Paragraph("INFORME DE ENSAYE DE LABORATORIO - CONTROL DE CALIDAD GEOTÉCNICO", titulo_style))
    story.append(Paragraph(f"Obra: {obra_nombre}", subtitulo_style))
    story.append(Spacer(1, 4))

    cbr_esp = m.get('cbr_esp', {})
    try:
        gc_val = float(cbr_esp.get('Grado_Comp_Real', 100.0))
        mvs_suelta_v = float(m.get('MV_Suelta', 1.500))
    except (ValueError, TypeError):
        gc_val, mvs_suelta_v = 100.0, 1.500

    datos_header = [
        [Paragraph("<b>No. Muestra:</b>", celda_body), Paragraph(str(m['ID']), celda_body), Paragraph("<b>Banco / Calidad:</b>", celda_body), Paragraph(f"{m['Banco']} ({m['Calidad']})", celda_body)],
        [Paragraph("<b>Cliente:</b>", celda_body), Paragraph(str(m['Cliente']), celda_body), Paragraph("<b>Contratista:</b>", celda_body), Paragraph(str(m['Contratista']), celda_body)],
        [Paragraph("<b>Localización:</b>", celda_body), Paragraph(str(m['Localizacion']), celda_body), Paragraph("<b>Tramo:</b>", celda_body), Paragraph(str(m['Tramo']), celda_body)],
        [Paragraph("<b>Clasificación SUCS:</b>", celda_body), Paragraph(f"<b>{m['SUCS']}</b>", celda_body), Paragraph("<b>MVS Suelta:</b>", celda_body), Paragraph(f"<b>{mvs_suelta_v:.3f} g/cm³</b>", celda_body)],
        [Paragraph("<b>Grado Compactación:</b>", celda_body), Paragraph(f"<b>{gc_val:.1f} %</b>", celda_body), Paragraph("<b>Masa Inicial Gruesa:</b>", celda_body), Paragraph(f"{float(m.get('Masa_Gruesa', 0.0)):.1f} g", celda_body)]
    ]

    t_header = Table(datos_header, colWidths=[110, 165, 100, 185])
    t_header.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#EDF2F7')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 1.5),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 3))

    story.append(Paragraph("1. GRANULOMETRÍA Y LÍMITES DE ATTERBERG", seccion_style))
    gran_table_data = [[Paragraph("Malla", celda_head), Paragraph("M. Ret (g)", celda_head), Paragraph("% Ret. Parc", celda_head), Paragraph("% Ret. Acum", celda_head), Paragraph("% Pasa", celda_head)]]
    for _, row in m['df_gran'].iterrows():
        gran_table_data.append([
            Paragraph(str(row['Malla']), celda_body), Paragraph(f"{row['Masa Retenida (g)']:.1f}", celda_body), Paragraph(f"{row['% Retenido Parcial']:.1f}", celda_body), Paragraph(f"{row['% Retenido Acumulado']:.1f}", celda_body), Paragraph(f"{row['% Que Pasa']:.1f}", celda_body)
        ])
    t_gran = Table(gran_table_data, colWidths=[100, 115, 115, 115, 115])
    t_gran.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2B6CB0')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F7FAFC')]),
        ('PADDING', (0,0), (-1,-1), 1),
    ]))
    story.append(t_gran)
    story.append(Spacer(1, 3))

    try:
        cbr_final_val = float(cbr_esp.get('CBR_Final', m.get('CBR', 80.0)))
        exp_final_val = float(cbr_esp.get('Exp_Calc', m.get('Expansion', 0.10)))
        wopt_v = float(m.get('W_Opt', 8.5))
        mvs_esp_v = float(cbr_esp.get('MV_Seca', 2.050))
        
        df_p_inf = m.get('df_proctor', pd.DataFrame())
        if 'MV_Max' in m and m['MV_Max'] is not None:
            mvsm_v = float(m['MV_Max'])
        elif 'M.V. Seca (g/cm³)' in df_p_inf.columns and len(df_p_inf) > 0:
            mvsm_v = float(df_p_inf['M.V. Seca (g/cm³)'].max())
        else:
            mvsm_v = 2.050
    except (ValueError, TypeError):
        cbr_final_val, exp_final_val, mvsm_v, wopt_v, mvs_esp_v = 80.0, 0.10, 2.050, 8.5, 2.050

    story.append(Paragraph(f"2. COMPACTACIÓN PROCTOR Y CBR (MVSM: {mvsm_v:.3f} g/cm³ | CBR: {cbr_final_val:.1f} % | Exp: {exp_final_val:.2f} %)", seccion_style))
    cbr_head_data = [
        [Paragraph(f"<b>MVSM:</b> {mvsm_v:.3f} g/cm³", celda_body), Paragraph(f"<b>W Óptima:</b> {wopt_v:.1f} %", celda_body), Paragraph(f"<b>MVS Suelta:</b> {mvs_suelta_v:.3f} g/cm³", celda_body), Paragraph(f"<b>Molde Proc:</b> {m['Molde_ID']}", celda_body)],
        [Paragraph(f"<b>Molde CBR:</b> {cbr_esp.get('Molde_ID', 'CBR-01')}", celda_body), Paragraph(f"<b>MVS Espécimen:</b> {mvs_esp_v:.3f} g/cm³", celda_body), Paragraph(f"<b>Expansión:</b> <b>{exp_final_val:.2f} %</b>", celda_body), Paragraph(f"<b>CBR a 0.1\":</b> <b>{cbr_final_val:.1f} %</b>", celda_body)]
    ]
    t_cbr_head = Table(cbr_head_data, colWidths=[140, 140, 140, 140])
    t_cbr_head.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F7FAFC')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E0')),
        ('PADDING', (0,0), (-1,-1), 1.5),
    ]))
    story.append(t_cbr_head)

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def generar_pdf_con_plantilla_imagen(m, imagen_plantilla_bytes, obra_nombre, modo_calibracion=False):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    ancho, alto = letter # 612 x 792 pt

    if imagen_plantilla_bytes is not None:
        img = ImageReader(io.BytesIO(imagen_plantilla_bytes) if isinstance(imagen_plantilla_bytes, bytes) else imagen_plantilla_bytes)
        c.drawImage(img, 0, 0, width=ancho, height=alto)

    if modo_calibracion:
        c.setFont("Helvetica", 4.5)
        c.setStrokeColor(colors.HexColor('#FFBABA'))
        c.setLineWidth(0.3)
        for x in range(0, int(ancho), 10):
            if x % 50 != 0:
                c.line(x, 0, x, alto)
        for y in range(0, int(alto), 10):
            if y % 50 != 0:
                c.line(0, y, ancho, y)

        c.setStrokeColor(colors.red)
        c.setFillColor(colors.red)
        c.setLineWidth(0.7)
        for x in range(0, int(ancho), 50):
            c.line(x, 0, x, alto)
            c.drawString(x + 1, 8, str(x))
            c.drawString(x + 1, alto - 12, str(x))
        for y in range(0, int(alto), 50):
            c.line(0, y, ancho, y)
            c.drawString(6, y + 1, str(y))
            c.drawString(ancho - 22, y + 1, str(y))

    # Tono grafito profesional
    c.setFillColor(colors.HexColor('#262626'))

    # 1. ENCABEZADO Y DATOS DE OBRA (TODOS EN NEGRITA)
    c.setFont(FUENTE_BOLD, 6.8)
    c.drawString(190, 700, str(obra_nombre))
    c.drawString(140, 685, str(m.get('Localizacion', '')))
    c.drawString(140, 672, str(m.get('Tramo', '')))
    c.drawString(140, 657, str(m.get('Cliente', '')))
    c.drawString(140, 642, str(m.get('ID', '')))

    # Contratista y las tres fechas en negrita
    c.drawString(392, 685, str(m.get('Contratista', '')))
    c.drawString(392, 672, str(m.get('F_Recepcion', '')))
    c.drawString(392, 658, str(m.get('F_Ensaye', '')))
    c.drawString(392, 642, str(m.get('F_Informe', '')))

    # 2. FORMULARIO DE CAMPO (EN NEGRITA)
    c.drawString(140, 605, str(m.get('Muestra_Tomada_En', '')))
    c.drawString(140, 592, str(m.get('Localizacion', '')))
    c.drawString(140, 580, str(m.get('Procedencia', '')))
    c.drawString(140, 567, str(m.get('Para_Utilizarse_En', '')))

    # 3. GRANULOMETRÍA (Regular, Columna X = 270)
    c.setFont(FUENTE_REGULAR, 6.8)
    df_g = m.get('df_gran', pd.DataFrame())
    
    def get_val_malla(malla_nombre, columna):
        if 'Malla' in df_g.columns and malla_nombre in df_g['Malla'].values:
            val = df_g.loc[df_g['Malla'] == malla_nombre, columna].values[0]
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0
        return 0.0

    ret_3pulg = get_val_malla('3"', '% Retenido Acumulado')
    pasa_no4 = get_val_malla('No.4', '% Que Pasa')
    pasa_no40 = get_val_malla('No.40', '% Que Pasa')
    pasa_no200 = get_val_malla('No.200', '% Que Pasa')

    tam_max_str = '3"' if ret_3pulg > 0.0 else '1 1/2"'
    c.drawString(270, 518, tam_max_str)
    c.drawString(270, 505, f"{ret_3pulg:.1f}")
    c.drawString(270, 492, f"{pasa_no4:.1f}")
    c.drawString(270, 480, f"{pasa_no40:.1f}")
    c.drawString(270, 467, f"{pasa_no200:.1f}")

    # 4. LÍMITES DE ATTERBERG (Regular, Columna X = 270)
    try:
        ll_v = float(m.get('LL', 0.0))
        lp_v = float(m.get('LP', 0.0))
        ip_v = float(m.get('IP', 0.0))
    except (ValueError, TypeError):
        ll_v, lp_v, ip_v = 0.0, 0.0, 0.0

    c.drawString(270, 453, f"{ll_v:.1f}")
    c.drawString(270, 440, f"{lp_v:.1f}")
    c.drawString(270, 427, f"{ip_v:.1f}")

    # 5. PESOS VOLUMÉTRICOS, COMPACTACIÓN, CBR Y EXPANSIÓN
    df_p = m.get('df_proctor', pd.DataFrame())
    mvsm_val = None
    if 'MV_Max' in m and m['MV_Max'] is not None:
        try:
            mvsm_val = float(m['MV_Max'])
        except (ValueError, TypeError):
            pass

    if mvsm_val is None and 'M.V. Seca (g/cm³)' in df_p.columns and len(df_p) > 0:
        try:
            mvsm_val = float(df_p['M.V. Seca (g/cm³)'].max())
        except (ValueError, TypeError):
            pass

    if mvsm_val is None:
        mvsm_val = 2.050

    try:
        mvs_suelta_val = float(m.get('MV_Suelta', 1.500))
        w_opt_val = float(m.get('W_Opt', 8.5))
    except (ValueError, TypeError):
        mvs_suelta_val, w_opt_val = 1.500, 8.5

    c.drawString(270, 414, f"{mvs_suelta_val:.3f}")
    c.drawString(270, 401, f"{mvsm_val:.3f}")
    c.drawString(270, 388, f"{w_opt_val:.1f}")

    cbr_d = m.get('cbr_esp', {})
    try:
        cbr_val = float(cbr_d.get('CBR_Final', m.get('CBR', 80.0)))
        exp_val = float(cbr_d.get('Exp_Calc', m.get('Expansion', 0.10)))
    except (ValueError, TypeError):
        cbr_val, exp_val = 80.0, 0.10

    c.drawString(270, 375, f"{cbr_val:.1f}")
    c.drawString(270, 362, f"{exp_val:.2f}")
    
    # SUCS fijado en X=223, Y=350
    c.drawString(223, 350, str(m.get('SUCS', '')))

    # 6. OBSERVACIONES
    c.drawString(140, 160, str(m.get('Observaciones', ''))[:95])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# ==============================================================================
# 3. INICIALIZACIÓN DE ESTADO GLOBAL
# ==============================================================================

if 'bancos_materiales' not in st.session_state:
    st.session_state['bancos_materiales'] = {
        "Banco Principal": {
            "Base Hidráulica": {
                "ll": 25.0, "lp": 12.0, "mv_suelta": 1.510, "mv_max": 2.050, 
                "w_opt": 8.5, "cbr": 80.0, "exp": 0.10,
                "masa_g": 18000.0, "masa_f": 350.0, "pct_lav": 4.5,
                "pasa_g_ref": [100.0, 100.0, 95.0, 85.0, 70.0, 55.0, 42.0],
                "pasa_f_ref": [30.0, 22.0, 16.0, 12.0, 8.0, 5.0, 3.0]
            }
        }
    }

if 'catalogo_moldes' not in st.session_state:
    st.session_state['catalogo_moldes'] = {
        "Chico (4\")": {"id": "M-04", "volumen": 944.0, "peso": 3250.0},
        "Grande (6\")": {"id": "MG-06", "volumen": 2124.0, "peso": 5820.0}
    }

if 'molde_cbr_config' not in st.session_state:
    st.session_state['molde_cbr_config'] = {
        "id": "CBR-01",
        "diametro_cm": 15.24,
        "altura_molde_cm": 17.78,
        "altura_disco_cm": 6.14,
        "peso": 5820.0
    }

if 'molde_suelta_config' not in st.session_state:
    st.session_state['molde_suelta_config'] = {
        "id": "REC-10L",
        "volumen": 10000.0,
        "peso": 5250.0
    }

if 'base_datos_bancos' not in st.session_state:
    st.session_state['base_datos_bancos'] = {}

if 'datos_campo_persistentes' not in st.session_state:
    st.session_state['datos_campo_persistentes'] = {
        'tomada_en': 'Banco de Préstamo',
        'procedencia': 'Banco Principal',
        'para_utilizarse': 'Capa de Base Hidráulica',
        'observaciones': 'El material analizado cumple satisfactoriamente con la normatividad del proyecto.'
    }

# ==============================================================================
# 4. SIDEBAR (CONFIGURACIÓN DE OBRA, BANCO, CALIDAD Y GENERADOR)
# ==============================================================================

st.sidebar.header("⚙️ Configuración y Obra")

obra_nombre_oficial = "Construcción de la Autopista 'El peyote - matehuala' - Carretera 75 D Matehuala"
st.sidebar.markdown(f"**Obra:**\n{obra_nombre_oficial}")

cliente_fijo = "URBA Ingeniería"
contratista_ingresado = st.sidebar.text_input("Contratista:", value="Constructora General SA de CV")

tramos_config = {
    "Tramo 3 (Del km 55+000 al km 85+000)": {"codigo": "P003", "sub": "Tramo 3"},
    "Tramo 4 (Del km 85+000 al km 116+500)": {"codigo": "P003", "sub": "Tramo 4"},
    "Construcción Entronque Matehuala, Autopista 75 D Matehuala": {"codigo": "P004", "sub": "Entronque Matehuala"}
}

tramo_seleccionado_nombre = st.sidebar.selectbox("Selecciona Tramo:", list(tramos_config.keys()))
tramo_info = tramos_config[tramo_seleccionado_nombre]

banco_seleccionado_nombre = st.sidebar.selectbox("Selecciona Banco de Material:", list(st.session_state['bancos_materiales'].keys()))
calidades_disponibles = list(st.session_state['bancos_materiales'][banco_seleccionado_nombre].keys())
calidad_seleccionada = st.sidebar.selectbox("Selecciona Calidad / Capa:", calidades_disponibles)
banco_props = st.session_state['bancos_materiales'][banco_seleccionado_nombre][calidad_seleccionada]

with st.sidebar.expander("➕ Administrar / Editar Bancos y Calidades"):
    tipo_gestion = st.radio("Acción:", ["Editar Calidad Actual", "Agregar Calidad al Banco Actual", "Nuevo Banco"])

    if tipo_gestion == "Editar Calidad Actual":
        nb_nombre = banco_seleccionado_nombre
        nc_nombre = calidad_seleccionada
        st.info(f"Editando: **{banco_seleccionado_nombre}** $\\to$ **{calidad_seleccionada}**")
        p_base = banco_props
    elif tipo_gestion == "Agregar Calidad al Banco Actual":
        nb_nombre = banco_seleccionado_nombre
        nc_nombre = st.text_input("Nombre Nueva Calidad:", value="Subbase")
        p_base = {
            "ll": 28.5, "lp": 15.0, "mv_suelta": 1.450, "mv_max": 1.960,
            "w_opt": 10.2, "cbr": 52.0, "exp": 0.25,
            "masa_g": 18000.0, "masa_f": 350.0, "pct_lav": 4.5,
            "pasa_g_ref": [100.0, 100.0, 95.0, 85.0, 70.0, 55.0, 42.0],
            "pasa_f_ref": [30.0, 22.0, 16.0, 12.0, 8.0, 5.0, 3.0]
        }
    else:
        nb_nombre = st.text_input("Nombre Nuevo Banco:")
        nc_nombre = st.text_input("Calidad Inicial:", value="Base Hidráulica")
        p_base = {
            "ll": 25.0, "lp": 12.0, "mv_suelta": 1.510, "mv_max": 2.050,
            "w_opt": 8.5, "cbr": 80.0, "exp": 0.10,
            "masa_g": 18000.0, "masa_f": 350.0, "pct_lav": 4.5,
            "pasa_g_ref": [100.0, 100.0, 95.0, 85.0, 70.0, 55.0, 42.0],
            "pasa_f_ref": [30.0, 22.0, 16.0, 12.0, 8.0, 5.0, 3.0]
        }

    st.markdown("--- **Parámetros Geotécnicos de Referencia** ---")
    p_mvm = st.number_input("Masa Vol. Seca Máx. (MVSM) (g/cm³):", value=float(p_base["mv_max"]), format="%.3f")
    p_wopt = st.number_input("Humedad Óptima (%):", value=float(p_base["w_opt"]))
    p_cbr = st.number_input("CBR de Diseño (%):", value=float(p_base["cbr"]))
    p_exp = st.number_input("Expansión (%):", value=float(p_base["exp"]), format="%.2f")
    p_ll = st.number_input("Límite Líquido (LL) %:", value=float(p_base["ll"]))
    p_lp = st.number_input("Límite Plástico (LP) %:", value=float(p_base["lp"]))
    p_mvs = st.number_input("Masa Vol. Suelta (g/cm³):", value=float(p_base["mv_suelta"]), format="%.3f")

    st.markdown("--- **1. Fracción Gruesa (% Que Pasa)** ---")
    masa_ini_gruesa = st.number_input("Masa Inicial Gruesa (g):", value=float(p_base.get("masa_g", 18000.0)))
    df_gruesa_ed = st.data_editor(pd.DataFrame({
        'Malla': ['3"', '2"', '1 1/2"', '1"', '3/4"', '3/8"', 'No.4'],
        '% Que Pasa': p_base.get("pasa_g_ref", [100.0, 100.0, 95.0, 85.0, 70.0, 55.0, 42.0])
    }), hide_index=True)

    st.markdown("--- **2. Fracción Fina (% Que Pasa)** ---")
    masa_ini_fina = st.number_input("Masa Inicial Fina (g):", value=float(p_base.get("masa_f", 350.0)))
    pct_lavado_ref = st.number_input("% Pérdida por Lavado:", value=float(p_base.get("pct_lav", 4.5)))
    df_fina_ed = st.data_editor(pd.DataFrame({
        'Malla': ['No.10', 'No.20', 'No.40', 'No.60', 'No.100', 'No.200', 'Pasa No.200'],
        '% Que Pasa': p_base.get("pasa_f_ref", [30.0, 22.0, 16.0, 12.0, 8.0, 5.0, 3.0])
    }), hide_index=True)

    if st.button("💾 Guardar Banco / Calidad"):
        if nb_nombre.strip() and nc_nombre.strip():
            p_g_vals = [round(float(x), 1) for x in df_gruesa_ed['% Que Pasa'].tolist()]
            p_f_vals = [round(float(x), 1) for x in df_fina_ed['% Que Pasa'].tolist()]

            if nb_nombre not in st.session_state['bancos_materiales']:
                st.session_state['bancos_materiales'][nb_nombre] = {}

            st.session_state['bancos_materiales'][nb_nombre][nc_nombre] = {
                "ll": float(p_ll), "lp": float(p_lp), 
                "mv_suelta": round(float(p_mvs), 3), 
                "mv_max": round(float(p_mvm), 3), 
                "w_opt": float(p_wopt), 
                "cbr": float(p_cbr), 
                "exp": float(p_exp),
                "masa_g": float(masa_ini_gruesa), 
                "masa_f": float(masa_ini_fina), 
                "pct_lav": float(pct_lavado_ref),
                "pasa_g_ref": p_g_vals, 
                "pasa_f_ref": p_f_vals
            }
            st.success("¡Guardado con éxito! Ahora puedes generar lote o actualizar el existente.")
            st.rerun()
        else:
            st.error("Completa los nombres requeridos.")

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 Parámetros de Generación")
grado_compactacion_ingresado = st.sidebar.number_input(
    "Grado de Compactación Objetivo CBR (%):", 
    min_value=85.0, max_value=105.0, value=100.0, step=0.5
)

fecha_min_default = datetime.now().date() - timedelta(days=60)
fecha_inicio = st.sidebar.date_input("Fecha Inicial:", value=fecha_min_default)
fecha_fin = st.sidebar.date_input("Fecha Final:", value=datetime.now().date())
num_muestras = st.sidebar.slider("Número de muestras a generar:", 1, 20, 5)
consecutivo_inicial = st.sidebar.number_input("Consecutivo Inicial:", min_value=1, value=1, step=1)

db_key = f"{banco_seleccionado_nombre} | {calidad_seleccionada} | {tramo_seleccionado_nombre}"

if db_key not in st.session_state['base_datos_bancos']:
    st.session_state['base_datos_bancos'][db_key] = []

if st.sidebar.button("🔄 Generar Nuevo Lote para esta Calidad", type="primary"):
    if fecha_inicio > fecha_fin:
        st.error("La fecha inicial no puede ser posterior a la fecha final.")
    else:
        current_props = st.session_state['bancos_materiales'][banco_seleccionado_nombre][calidad_seleccionada]
        st.session_state['base_datos_bancos'][db_key] = generar_muestras_logic(
            fecha_inicio, fecha_fin, num_muestras, consecutivo_inicial, cliente_fijo, contratista_ingresado, 
            tramo_seleccionado_nombre, tramo_info, banco_seleccionado_nombre, calidad_seleccionada, current_props,
            grado_compactacion_ingresado
        )
        st.success("¡Nuevo lote generado exitosamente!")
        st.rerun()

if st.sidebar.button("⚡ Actualizar Lote Actual con Nueva Referencia"):
    if len(st.session_state['base_datos_bancos'][db_key]) > 0:
        current_props = st.session_state['bancos_materiales'][banco_seleccionado_nombre][calidad_seleccionada]
        st.session_state['base_datos_bancos'][db_key] = recalcular_muestras_existentes(
            st.session_state['base_datos_bancos'][db_key], current_props, grado_compactacion_ingresado
        )
        st.success("¡Lote existente actualizado con los nuevos moldes y MVS Suelta!")
        st.rerun()
    else:
        st.warning("No hay muestras generadas para actualizar. Presiona 'Generar Nuevo Lote'.")

muestras_actuales = st.session_state['base_datos_bancos'][db_key]

# ==============================================================================
# 5. PESTAÑAS PRINCIPALES
# ==============================================================================

tab_captura, tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Resumen Maestro de Captura",
    f"📊 Bitácora: {calidad_seleccionada}", 
    "🔬 Auditoría Integral de Ensayes", 
    "📄 Detalle e Informe PDF",
    "📚 Catálogo de Bancos y Moldes"
])

# --- PESTAÑA 1: RESUMEN MAESTRO PARA CAPTURA RÁPIDA ---
with tab_captura:
    st.subheader(f"📋 Sábana Maestra de Captura de Laboratorio")
    st.markdown(f"**Obra:** {obra_nombre_oficial} | **Banco:** `{banco_seleccionado_nombre}` | **Capa:** `{calidad_seleccionada}`")
    
    if len(muestras_actuales) > 0:
        sabana_captura = []
        for m in muestras_actuales:
            cbr_d = m.get('cbr_esp', {})
            df_g = m.get('df_gran', pd.DataFrame())
            d_suelta = m.get('datos_suelta', {})

            pasa_200 = df_g.loc[df_g['Malla'] == 'No.200', '% Que Pasa'].values[0] if ('Malla' in df_g.columns and 'No.200' in df_g['Malla'].values) else 0.0
            pasa_4 = df_g.loc[df_g['Malla'] == 'No.4', '% Que Pasa'].values[0] if ('Malla' in df_g.columns and 'No.4' in df_g['Malla'].values) else 0.0

            df_proc_cap = m.get('df_proctor', pd.DataFrame())
            if 'MV_Max' in m and m['MV_Max'] is not None:
                mvsm_captura = float(m['MV_Max'])
            elif 'M.V. Seca (g/cm³)' in df_proc_cap.columns and len(df_proc_cap) > 0:
                mvsm_captura = float(df_proc_cap['M.V. Seca (g/cm³)'].max())
            else:
                mvsm_captura = 2.050

            sabana_captura.append({
                'No. Muestra': m.get('ID', '-'),
                'Fecha Recep.': m.get('F_Recepcion', '-'),
                'Tramo': m.get('Tramo', '-'),
                'Muestra Tomada En': m.get('Muestra_Tomada_En', 'Banco de Préstamo'),
                'Localización': m.get('Localizacion', '-'),
                'Procedencia': m.get('Procedencia', m.get('Banco', '-')),
                'Para Utilizarse En': m.get('Para_Utilizarse_En', f"Capa de {m.get('Calidad', '')}"),
                'Observaciones': m.get('Observaciones', '-'),
                'SUCS': m.get('SUCS', '-'),
                '% Que Pasa No.4': round(float(pasa_4), 1),
                '% Que Pasa No.200': round(float(pasa_200), 1),
                'LL (%)': round(float(m.get('LL', 0.0)), 1),
                'LP (%)': round(float(m.get('LP', 0.0)), 1),
                'IP (%)': round(float(m.get('IP', 0.0)), 1),
                'MVS Suelta (g/cm³)': round(float(m.get('MV_Suelta', 1.500)), 3),
                'Peso Rec. Suelta (g)': round(float(d_suelta.get('Peso_Recipiente_g', 5250.0)), 1),
                'Vol. Rec. Suelta (cm³)': round(float(d_suelta.get('Volumen_Recipiente_cm3', 10000.0)), 1),
                'Báscula Suelta (g)': round(float(d_suelta.get('Peso_Total_Rec_Suelo_g', 0.0)), 1),
                'Suelo Seco Suelta (g)': round(float(d_suelta.get('Peso_Suelo_Seco_g', 0.0)), 1),
                'w_ópt (%)': round(float(m.get('W_Opt', 0.0)), 1),
                'MVSM (g/cm³)': round(float(mvsm_captura), 3),
                'Molde CBR ID': cbr_d.get('Molde_ID', '-'),
                'Alt. Suelo H (cm)': round(float(cbr_d.get('Altura_Suelo_cm', 11.64)), 2),
                'Vol. CBR (cm³)': round(float(cbr_d.get('Volumen_cm3', 2124.0)), 1),
                'Peso Molde CBR (g)': round(float(cbr_d.get('Peso_Molde_g', 5820.0)), 1),
                'Báscula Molde+Suelo (g)': round(float(cbr_d.get('Molde_Suelo_g', 0.0)), 1),
                'Suelo Húmedo CBR (g)': round(float(cbr_d.get('Suelo_Humedo_g', 0.0)), 1),
                'Grado Comp. Real (%)': round(float(cbr_d.get('Grado_Comp_Real', 100.0)), 1),
                'Expansión (%)': round(float(cbr_d.get('Exp_Calc', 0.0)), 2),
                'CBR a 0.1" (%)': round(float(cbr_d.get('CBR_01', 0.0)), 1)
            })

        df_captura = pd.DataFrame(sabana_captura)
        st.dataframe(df_captura, use_container_width=True)

        csv_data = df_captura.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📊 Descargar Sábana de Captura (CSV para Excel)",
            data=csv_data,
            file_name=f"Sabana_Captura_{banco_seleccionado_nombre}_{calidad_seleccionada}.csv",
            mime="text/csv",
            type="primary"
        )
    else:
        st.info("No hay muestras generadas todavía. Genera un nuevo lote desde la barra lateral.")

with tab1:
    st.subheader(f"Registros - Banco: `{banco_seleccionado_nombre}` | Calidad: `{calidad_seleccionada}`")
    st.markdown(f"**Obra:** {obra_nombre_oficial} | **Tramo:** {tramo_seleccionado_nombre}")

    if len(muestras_actuales) > 0:
        resumen_list = []
        for m in muestras_actuales:
            cbr_d = m.get('cbr_esp', {})
            gc_val = cbr_d.get('Grado_Comp_Real', 100.0)
            cbr_val = cbr_d.get('CBR_Final', m.get('CBR', 80.0))
            exp_val = cbr_d.get('Exp_Calc', m.get('Expansion', 0.10))

            df_proc_tab1 = m.get('df_proctor', pd.DataFrame())
            if 'MV_Max' in m and m['MV_Max'] is not None:
                mvsm_tab1 = float(m['MV_Max'])
            elif 'M.V. Seca (g/cm³)' in df_proc_tab1.columns and len(df_proc_tab1) > 0:
                mvsm_tab1 = float(df_proc_tab1['M.V. Seca (g/cm³)'].max())
            else:
                mvsm_tab1 = 2.050

            resumen_list.append({
                'Muestra': m.get('ID', '-'),
                'F. Recepción': m.get('F_Recepcion', '-'),
                'Tramo': m.get('Tramo', '-'),
                'LL (%)': round(float(m.get('LL', 0.0)), 1),
                'IP (%)': round(float(m.get('IP', 0.0)), 1),
                'MVS Suelta': f"{float(m.get('MV_Suelta', 1.500)):.3f}",
                'MVSM': f"{float(mvsm_tab1):.3f}",
                'W Ópt (%)': round(float(m.get('W_Opt', 0.0)), 1),
                'Grado Comp (%)': f"{float(gc_val):.1f}%",
                'CBR (%)': round(float(cbr_val), 1),
                'Exp (%)': round(float(exp_val), 2),
                'SUCS': m.get('SUCS', '-')
            })
        st.dataframe(pd.DataFrame(resumen_list))

        pdf_lote_bytes = generar_pdf_lote_resumen(muestras_actuales, obra_nombre_oficial, banco_seleccionado_nombre, calidad_seleccionada)
        st.download_button(
            label="📥 Descargar Reporte Consolidado de Lote (PDF)",
            data=pdf_lote_bytes,
            file_name=f"Reporte_Lote_{banco_seleccionado_nombre}_{calidad_seleccionada}.pdf",
            mime="application/pdf",
            type="primary"
        )
    else:
        st.info("No hay registros. Genera un lote desde la barra lateral.")

with tab2:
    st.subheader(f"🔬 Auditoría Integral de Laboratorio - [{calidad_seleccionada}]")
    if len(muestras_actuales) > 0:
        muestras_ids = [m['ID'] for m in muestras_actuales]
        muestra_edit_id = st.selectbox("Selecciona la muestra para inspeccionar:", muestras_ids)

        m_idx = next(i for i, m in enumerate(muestras_actuales) if m['ID'] == muestra_edit_id)
        m_a_editar = muestras_actuales[m_idx]

        st.markdown(f"**Muestra Seleccionada:** `{m_a_editar['ID']}`")

        st.markdown("#### 📝 Datos de Campo y Formulario de la Muestra")
        cfg_campo = st.session_state['datos_campo_persistentes']

        val_tomada = m_a_editar.get('Muestra_Tomada_En') or cfg_campo['tomada_en']
        val_loc = m_a_editar.get('Localizacion', '')
        val_proc = m_a_editar.get('Procedencia') or cfg_campo['procedencia']
        val_util = m_a_editar.get('Para_Utilizarse_En') or cfg_campo['para_utilizarse']
        val_obs = m_a_editar.get('Observaciones') or cfg_campo['observaciones']

        col_f1, col_f2 = st.columns(2)
        n_tomada_en = col_f1.text_input("Muestra tomada en:", value=str(val_tomada), key=f"f_tomada_{m_a_editar['ID']}")
        n_localizacion = col_f2.text_input("Localización:", value=str(val_loc), key=f"f_loc_{m_a_editar['ID']}")
        
        col_f3, col_f4 = st.columns(2)
        n_procedencia = col_f3.text_input("Procedencia:", value=str(val_proc), key=f"f_proc_{m_a_editar['ID']}")
        n_para_util = col_f4.text_input("Para utilizarse en:", value=str(val_util), key=f"f_util_{m_a_editar['ID']}")
        
        n_observaciones = st.text_area("Observaciones:", value=str(val_obs), key=f"f_obs_{m_a_editar['ID']}")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Guardar Datos en Esta Muestra", key=f"btn_guardar_form_{m_a_editar['ID']}"):
                st.session_state['base_datos_bancos'][db_key][m_idx]['Muestra_Tomada_En'] = n_tomada_en
                st.session_state['base_datos_bancos'][db_key][m_idx]['Localizacion'] = n_localizacion
                st.session_state['base_datos_bancos'][db_key][m_idx]['Procedencia'] = n_procedencia
                st.session_state['base_datos_bancos'][db_key][m_idx]['Para_Utilizarse_En'] = n_para_util
                st.session_state['base_datos_bancos'][db_key][m_idx]['Observaciones'] = n_observaciones

                st.session_state['datos_campo_persistentes']['tomada_en'] = n_tomada_en
                st.session_state['datos_campo_persistentes']['procedencia'] = n_procedencia
                st.session_state['datos_campo_persistentes']['para_utilizarse'] = n_para_util
                st.session_state['datos_campo_persistentes']['observaciones'] = n_observaciones

                st.success("¡Datos guardados y conservados para las demás muestras!")
                st.rerun()

        with col_btn2:
            if st.button("📋 Aplicar Estos Datos a TODO el Lote", key=f"btn_aplicar_todos_{m_a_editar['ID']}"):
                st.session_state['datos_campo_persistentes']['tomada_en'] = n_tomada_en
                st.session_state['datos_campo_persistentes']['procedencia'] = n_procedencia
                st.session_state['datos_campo_persistentes']['para_utilizarse'] = n_para_util
                st.session_state['datos_campo_persistentes']['observaciones'] = n_observaciones

                for idx_m in range(len(st.session_state['base_datos_bancos'][db_key])):
                    st.session_state['base_datos_bancos'][db_key][idx_m]['Muestra_Tomada_En'] = n_tomada_en
                    st.session_state['base_datos_bancos'][db_key][idx_m]['Procedencia'] = n_procedencia
                    st.session_state['base_datos_bancos'][db_key][idx_m]['Para_Utilizarse_En'] = n_para_util
                    st.session_state['base_datos_bancos'][db_key][idx_m]['Observaciones'] = n_observaciones

                st.success("¡Datos aplicados exitosamente a todas las muestras del lote!")
                st.rerun()

        st.markdown("---")
        
        # AUDITORÍA DIRECTA DE MASA VOLUMÉTRICA SECA SUELTA
        st.markdown("### 🪨 1. Masa Volumétrica Seca Suelta (MVS Suelta)")
        d_suelta = m_a_editar.get('datos_suelta', simular_mvs_suelta(m_a_editar.get('MV_Suelta', 1.500), st.session_state['molde_suelta_config']))
        
        col_s1, col_s2, col_s3 = st.columns(3)
        col_s1.metric("MVS Suelta", f"{d_suelta['MVS_Suelta']:.3f} g/cm³")
        col_s2.metric("Volumen Recipiente", f"{d_suelta['Volumen_Recipiente_cm3']:.0f} cm³")
        col_s3.metric("Peso Recipiente", f"{d_suelta['Peso_Recipiente_g']:.1f} g")

        st.markdown("**Pesadas Directas:**")
        st.markdown(f"- **Recipiente ID:** `{d_suelta.get('Recipiente_ID', 'REC-10L')}`")
        st.markdown(f"- **Lectura de Báscula (Recipiente + Suelo Seco):** `{d_suelta['Peso_Total_Rec_Suelo_g']:.1f} g`")
        st.markdown(f"- **Masa Neta de Suelo Seco Suelto:** `{d_suelta['Peso_Suelo_Seco_g']:.1f} g`")

        st.markdown("---")
        st.markdown("### 🚜 2. Prueba de CBR y Expansión")
        cbr_d = m_a_editar.get('cbr_esp', {})

        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        col_c1.metric("CBR a 0.1\"", f"{cbr_d.get('CBR_01', 80.0):.1f} %", f"Carga: {cbr_d.get('Carga_01_kgf', 1086.4):.1f} kgf")
        col_c2.metric("CBR a 0.2\"", f"{cbr_d.get('CBR_02', 80.0):.1f} %", f"Carga: {cbr_d.get('Carga_02_kgf', 1350.0):.1f} kgf")
        delta_l_calc = cbr_d.get('L_Fin_mm', 1.62) - cbr_d.get('L_Ini_mm', 1.50)
        col_c3.metric("Expansión", f"{cbr_d.get('Exp_Calc', 0.10):.2f} %", f"ΔL: {delta_l_calc:.2f} mm")
        col_c4.metric("Grado Compactación", f"{cbr_d.get('Grado_Comp_Real', 100.0):.1f} %", f"MVS: {cbr_d.get('MV_Seca', 2.050):.3f} g/cm³")

        col_geom1, col_geom2 = st.columns([1, 1])
        with col_geom1:
            st.markdown("**Parámetros Físicos del Espécimen:**")
            st.markdown(f"- **Molde CBR:** `{cbr_d.get('Molde_ID', 'CBR-01')}` | **Peso Molde:** `{cbr_d.get('Peso_Molde_g', 5820.0):.1f} g`")
            st.markdown(f"- **Diámetro Molde ($D$):** `{cbr_d.get('Diametro_cm', 15.24):.2f} cm` | **Área ($A$):** `{cbr_d.get('Area_cm2', 182.41):.2f} cm²`")
            st.markdown(f"- **Altura Molde:** `{cbr_d.get('Altura_Molde_cm', 17.78):.2f} cm` | **Disco:** `{cbr_d.get('Altura_Disco_cm', 6.14):.2f} cm`")
            st.markdown(f"- **Altura Suelo ($H$):** `{cbr_d.get('Altura_Suelo_cm', 11.64):.2f} cm` | **Volumen Espécimen ($V$):** `{cbr_d.get('Volumen_cm3', 2124.0):.1f} cm³`")
            st.markdown(f"- **Suelo Húmedo ($M_{{suelo}}$):** `{cbr_d.get('Suelo_Humedo_g', 4630.0):.1f} g` | **Molde + Suelo:** `{cbr_d.get('Molde_Suelo_g', 10450.0):.1f} g`")
            st.markdown(f"- **Humedad Inicial:** `{cbr_d.get('W_Ini', 8.5):.1f} %` (Tara: `{cbr_d.get('No_Tara', 'TC-01')}` | M.Tara: `{cbr_d.get('M_Tara_g', 100.0):.1f} g`)")
            st.markdown(f"- **Lectura Extensómetro Inicial:** `{cbr_d.get('L_Ini_mm', 1.50):.2f} mm` | Final: `{cbr_d.get('L_Fin_mm', 1.62):.2f} mm`")

        with col_geom2:
            st.markdown("**Curva de Penetración Registrada (kgf):**")
            st.dataframe(m_a_editar['df_penetracion'])

        st.markdown("---")
        st.markdown(f"### 🔨 3. Compactación MVSM (Proctor a 4 Puntos - Molde: `{m_a_editar['Molde_ID']}`)")
        st.dataframe(m_a_editar['df_proctor'])

        df_proc_aud = m_a_editar.get('df_proctor', pd.DataFrame())
        if 'MV_Max' in m_a_editar and m_a_editar['MV_Max'] is not None:
            mvsm_aud = float(m_a_editar['MV_Max'])
        elif 'M.V. Seca (g/cm³)' in df_proc_aud.columns and len(df_proc_aud) > 0:
            mvsm_aud = float(df_proc_aud['M.V. Seca (g/cm³)'].max())
        else:
            mvsm_aud = 2.050

        col_p1, col_p2, col_p3 = st.columns(3)
        col_p1.metric("M.V. Seca Máxima (MVSM)", f"{mvsm_aud:.3f} g/cm³")
        col_p2.metric("Humedad Óptima (W_opt)", f"{m_a_editar['W_Opt']:.1f} %")
        col_p3.metric("Volumen Molde", f"{m_a_editar['Vol_Molde']:.1f} cm³")

        st.markdown("---")
        col_sub1, col_sub2 = st.columns(2)
        with col_sub1:
            st.markdown("### 🧪 4. Límites de Atterberg")
            st.dataframe(m_a_editar['df_limites'])
            st.markdown(f"**LL:** `{m_a_editar['LL']:.1f}%` | **LP:** `{m_a_editar['LP']:.1f}%` | **IP:** `{m_a_editar['IP']:.1f}%`")

        with col_sub2:
            st.markdown("### ⚖️ 5. Granulometría Continua")
            st.dataframe(m_a_editar['df_gran'])
            st.markdown(f"**Masa Gruesa:** `{m_a_editar['Masa_Gruesa']:.1f} g` | **Masa Fina:** `{m_a_editar['Masa_Fina']:.1f} g` | **Lavado:** `{m_a_editar['Pct_Lavado']:.1f}%`")

    else:
        st.info("No hay muestras generadas para auditar.")

# --- PESTAÑA 3: DETALLE E INFORME PDF CON CARGA FIJA POR DEFECTO ---
with tab3:
    st.subheader("📄 Detalle e Informe Oficial en Plantilla de Imagen")
    if len(muestras_actuales) > 0:
        muestras_ids = [m['ID'] for m in muestras_actuales]
        muestra_pdf_id = st.selectbox("Selecciona muestra para generar su informe oficial:", muestras_ids, key="sel_pdf_plantilla")
        m_pdf = next(m for m in muestras_actuales if m['ID'] == muestra_pdf_id)

        col_cfg1, col_cfg2 = st.columns([2, 1])
        with col_cfg1:
            plantilla_file = st.file_uploader(
                "Subir o cambiar plantilla temporal (opcional):", 
                type=["png", "jpg", "jpeg"],
                key="uploader_plantilla"
            )
        with col_cfg2:
            ver_cuadricula = st.checkbox("Mostrar cuadrícula de calibración (X, Y) [Paso fino 10 pt]", value=False)

        nombre_archivo_limpio = f"{m_pdf['ID'].replace('/', '_').replace(':', '_')}.pdf"

        # DETECCIÓN DE PLANTILLA FIJA LOCAL EN LA CARPETA
        imagen_bytes = None
        if plantilla_file is not None:
            imagen_bytes = plantilla_file.read()
        else:
            for archivo_candidato in ["plantilla_oficial.png", "plantilla_oficial.jpg", "plantilla_oficial.jpeg"]:
                if os.path.exists(archivo_candidato):
                    with open(archivo_candidato, "rb") as f:
                        imagen_bytes = f.read()
                    break

        if imagen_bytes is not None:
            pdf_personalizado = generar_pdf_con_plantilla_imagen(m_pdf, imagen_bytes, obra_nombre_oficial, modo_calibracion=ver_cuadricula)

            st.download_button(
                label=f"📥 Descargar {nombre_archivo_limpio}",
                data=pdf_personalizado,
                file_name=nombre_archivo_limpio,
                mime="application/pdf",
                type="primary"
            )
        else:
            st.info("💡 Coloca 'plantilla_oficial.png' en la carpeta para carga fija o sube una imagen arriba.")
            pdf_generico = generar_pdf_informe(m_pdf, obra_nombre_oficial)
            st.download_button(
                label=f"📥 Descargar Informe Genérico - {nombre_archivo_limpio}",
                data=pdf_generico,
                file_name=nombre_archivo_limpio,
                mime="application/pdf"
            )
    else:
        st.info("No hay muestras generadas para mostrar el detalle.")

with tab4:
    st.subheader("📚 Catálogo de Bancos, Calidades y Moldes")
    
    st.markdown("### 🛢️ 1. Configuración de Moldes de Compactación (MVSM), CBR y MVS Suelta")
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown("**Moldes Proctor (Compactación MVSM):**")
        p_chico = st.number_input("Peso Molde 4\" Chico con Base (g):", value=float(st.session_state['catalogo_moldes']['Chico (4")']['peso']), step=10.0)
        v_chico = st.number_input("Volumen Calibrado Molde 4\" (cm³):", value=float(st.session_state['catalogo_moldes']['Chico (4")']['volumen']), step=1.0)
        
        p_grande = st.number_input("Peso Molde 6\" Grande con Base (g):", value=float(st.session_state['catalogo_moldes']['Grande (6")']['peso']), step=10.0)
        v_grande = st.number_input("Volumen Calibrado Molde 6\" (cm³):", value=float(st.session_state['catalogo_moldes']['Grande (6")']['volumen']), step=1.0)
    
    with col_m2:
        st.markdown("**Molde CBR y Espaciador:**")
        p_cbr_peso_tab4 = st.number_input("Peso Molde CBR (g):", value=float(st.session_state['molde_cbr_config']['peso']), step=10.0)
        p_cbr_diam = st.number_input("Diámetro Molde CBR (cm):", value=float(st.session_state['molde_cbr_config']['diametro_cm']), step=0.01)
        p_cbr_alt = st.number_input("Altura Total Molde CBR (cm):", value=float(st.session_state['molde_cbr_config']['altura_molde_cm']), step=0.01)
        p_cbr_disco = st.number_input("Altura Disco Espaciador (cm):", value=float(st.session_state['molde_cbr_config']['altura_disco_cm']), step=0.01)

    with col_m3:
        st.markdown("**Recipiente MVS Suelta (Directo):**")
        p_suelta_rec = st.number_input(
            "Peso Recipiente Suelta (g):", 
            value=float(st.session_state['molde_suelta_config']['peso']), 
            step=10.0,
            key='in_suelta_peso'
        )
        v_suelta_rec = st.number_input(
            "Volumen Recipiente Suelta (cm³):", 
            value=float(st.session_state['molde_suelta_config']['volumen']), 
            step=50.0,
            key='in_suelta_vol'
        )

    if st.button("💾 Guardar Cambios de Moldes y Recalcular Lote", type="primary"):
        st.session_state['catalogo_moldes']['Chico (4")']['peso'] = round(float(p_chico), 1)
        st.session_state['catalogo_moldes']['Chico (4")']['volumen'] = round(float(v_chico), 1)
        
        st.session_state['catalogo_moldes']['Grande (6")']['peso'] = round(float(p_grande), 1)
        st.session_state['catalogo_moldes']['Grande (6")']['volumen'] = round(float(v_grande), 1)

        st.session_state['molde_cbr_config']['peso'] = float(p_cbr_peso_tab4)
        st.session_state['molde_cbr_config']['diametro_cm'] = float(p_cbr_diam)
        st.session_state['molde_cbr_config']['altura_molde_cm'] = float(p_cbr_alt)
        st.session_state['molde_cbr_config']['altura_disco_cm'] = float(p_cbr_disco)

        st.session_state['molde_suelta_config']['peso'] = float(p_suelta_rec)
        st.session_state['molde_suelta_config']['volumen'] = float(v_suelta_rec)

        if len(st.session_state['base_datos_bancos'][db_key]) > 0:
            for idx in range(len(st.session_state['base_datos_bancos'][db_key])):
                tipo_m = st.session_state['base_datos_bancos'][db_key][idx]['Tipo_Molde']
                info_m = st.session_state['catalogo_moldes'][tipo_m]
                nuevo_p_m = float(info_m['peso'])
                nuevo_v_m = float(info_m['volumen'])
                
                st.session_state['base_datos_bancos'][db_key][idx]['Molde_ID'] = info_m['id']
                st.session_state['base_datos_bancos'][db_key][idx]['Vol_Molde'] = nuevo_v_m

                df_p = st.session_state['base_datos_bancos'][db_key][idx]['df_proctor'].copy()
                df_p['Molde ID'] = info_m['id']
                df_p['Volumen (cm³)'] = nuevo_v_m
                df_p['Peso Molde (g)'] = nuevo_p_m
                df_p['Suelo Húmedo (g)'] = np.round(df_p['M.V. Húmeda (g/cm³)'] * nuevo_v_m, 1)
                df_p['Molde + Suelo (g)'] = np.round(nuevo_p_m + df_p['Suelo Húmedo (g)'], 1)
                st.session_state['base_datos_bancos'][db_key][idx]['df_proctor'] = df_p

                cbr_dict = st.session_state['base_datos_bancos'][db_key][idx]['cbr_esp']
                h_suelo_cbr = round(float(p_cbr_alt) - float(p_cbr_disco), 2)
                area_cbr = round((math.pi * (float(p_cbr_diam) ** 2)) / 4.0, 2)
                vol_cbr_nuevo = round(area_cbr * h_suelo_cbr, 1)

                cbr_dict['Peso_Molde_g'] = float(p_cbr_peso_tab4)
                cbr_dict['Diametro_cm'] = float(p_cbr_diam)
                cbr_dict['Area_cm2'] = area_cbr
                cbr_dict['Altura_Molde_cm'] = float(p_cbr_alt)
                cbr_dict['Altura_Disco_cm'] = float(p_cbr_disco)
                cbr_dict['Altura_Suelo_cm'] = h_suelo_cbr
                cbr_dict['Volumen_cm3'] = vol_cbr_nuevo

                nuevo_suelo_hum_cbr = round(cbr_dict['MV_Humeda'] * vol_cbr_nuevo, 1)
                cbr_dict['Suelo_Humedo_g'] = nuevo_suelo_hum_cbr
                cbr_dict['Molde_Suelo_g'] = round(float(p_cbr_peso_tab4) + nuevo_suelo_hum_cbr, 1)
                
                delta_l_cm = (cbr_dict['Exp_Calc'] / 100.0) * h_suelo_cbr
                delta_l_mm = round(delta_l_cm * 10.0, 2)
                cbr_dict['L_Fin_mm'] = round(cbr_dict['L_Ini_mm'] + delta_l_mm, 2)
                cbr_dict['Delta_L_mm'] = delta_l_mm
                st.session_state['base_datos_bancos'][db_key][idx]['cbr_esp'] = cbr_dict

                try:
                    mv_suelta_actual = float(st.session_state['base_datos_bancos'][db_key][idx]['MV_Suelta'])
                except (ValueError, TypeError):
                    mv_suelta_actual = 1.500

                peso_suelo_seco = round(mv_suelta_actual * float(v_suelta_rec), 1)
                peso_tot_rec = round(float(p_suelta_rec) + peso_suelo_seco, 1)
                
                st.session_state['base_datos_bancos'][db_key][idx]['datos_suelta'] = {
                    "Recipiente_ID": "REC-10L",
                    "Volumen_Recipiente_cm3": float(v_suelta_rec),
                    "Peso_Recipiente_g": float(p_suelta_rec),
                    "Peso_Total_Rec_Suelo_g": peso_tot_rec,
                    "Peso_Suelo_Seco_g": peso_suelo_seco,
                    "MVS_Suelta": mv_suelta_actual
                }

            st.success("¡Geometría de CBR, Proctor y Recipiente MVS Suelta guardada y recalculada exitosamente!")
        else:
            st.success("¡Catálogo de moldes actualizado correctamente!")
        st.rerun()

    st.markdown("---")
    st.markdown("### 🏦 2. Resumen de Bancos Registrados")
    for banco_n, calidades_dict in st.session_state['bancos_materiales'].items():
        with st.expander(f"🏦 Banco: {banco_n}", expanded=True):
            for cal_n, props in calidades_dict.items():
                st.markdown(f"### Capa / Calidad: `{cal_n}`")
                col_c1, col_c2, col_c3 = st.columns(3)
                col_c1.metric("Límite Líquido (LL)", f"{props['ll']:.1f}%")
                col_c1.metric("Límite Plástico (LP)", f"{props['lp']:.1f}%")
                col_c2.metric("Masa Vol. Suelta", f"{props['mv_suelta']:.3f} g/cm³")
                col_c2.metric("Masa Vol. Seca Máx.", f"{props['mv_max']:.3f} g/cm³")
                col_c3.metric("Humedad Óptima", f"{props['w_opt']:.1f}%")
                col_c3.metric("CBR de Diseño", f"{props['cbr']:.1f}%")
                st.markdown(f"**Pérdida Lavado:** {props.get('pct_lav', 4.5):.1f}% | **Masa Gruesa:** {props.get('masa_g', 18000.0):.1f} g | **Masa Fina:** {props.get('masa_f', 350.0):.1f} g")
                st.markdown("---")
