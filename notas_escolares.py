import os
import io
import tempfile
import pandas as pd
import streamlit as st
import base64
import pdfplumber
import re
from streamlit_option_menu import option_menu
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
# Especificar la ruta de Ghostscript
if os.name == 'nt':  # Si es Windows
    os.environ["PATH"] += os.pathsep + r'C:\Program Files\gs\gs10.03.1\bin'
else:  # Si es Linux / Servidor Cloud
    os.environ["PATH"] += os.pathsep + r'/usr/bin'

# Crear un directorio temporal
TEMP = tempfile.TemporaryDirectory()

# Áreas curriculares oficiales requeridas para la evaluación literal
AREAS_OBJETIVO = [
    "ARTE Y CULTURA", 
    "CIENCIA Y TECNOLOGÍA", "CIENCIA Y TECNOLOGIA",
    "CIENCIAS SOCIALES", 
    "COMUNICACIÓN", "COMUNICACION",
    "DESARROLLO PERSONAL", "DESARROLLO PERSONAL, CIUDADANÍA Y CÍVICA",
    "EDUCACIÓN PARA EL TRABAJO", "EDUCACION PARA EL TRABAJO",
    "MATEMÁTICA", "MATEMATICA"
]

# Configurar la página y el fondo
st.set_page_config(initial_sidebar_state='collapsed', page_title="Sistema de Evaluación de Notas - UPCH", page_icon=":mortar_board:")

def get_base64_of_bin_file(bin_file):
    try:
        with open(bin_file, 'rb') as f:
            data = f.read()
        return base64.b64encode(data).decode()
    except FileNotFoundError:
        return ""

def set_background(image_file):
    bin_str = get_base64_of_bin_file(image_file)
    if bin_str:
        page_bg_img = f"""
        <style>
        .stApp {{
        background-image: url("data:image/png;base64,{bin_str}");
        background-size: cover;
        background-position: top left;
        background-repeat: no-repeat;
        background-attachment: fixed;
        }}
        </style>
        """
        st.markdown(page_bg_img, unsafe_allow_html=True)

# Establecer la imagen de fondo si existe
set_background('img.png') 

# =========================================================================
# MOTOR DE EXTRACCIÓN Y AUDITORÍA INTEGRADO (Fórmula de Precisión)
# =========================================================================
def procesar_constancia_literal(file_bytes):
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        texto_completo = ""
        todas_las_filas = []
        for pagina in pdf.pages:
            texto_completo += pagina.extract_text() or ""
            tablas = pagina.extract_tables()
            for t in tablas:
                todas_las_filas.extend(t)

    # 1. Extracción de DNI
    match_dni = re.search(r"DNI\s*(?:N\.?°?)?\s*(\d+)", texto_completo, re.IGNORECASE)
    dni = match_dni.group(1) if match_dni else "No encontrado"

    # 2. Extracción de Nombre Blindada (Estrategia combinada de doble verificación)
    nombre = "No encontrado"
    m1 = re.search(r"estudiante\s+([^,\n]+?)(?=,\s*con\s+DNI|\s+con\s+DNI)", texto_completo, re.IGNORECASE)
    if m1:
        nombre = m1.group(1).strip()
    else:
        m2 = re.search(r"([^\n]+?),\s*con\s+DNI", texto_completo, re.IGNORECASE)
        if m2:
            linea = m2.group(1).strip()
            nombre = re.sub(r".*?estudiante\s+", "", linea, flags=re.IGNORECASE).strip()

    # 3. Mapeo Dinámico de Columnas de Grados
    mapa_columnas = {}
    for fila in todas_las_filas:
        if fila and any("1.°" in str(celda) for celda in fila if celda):
            for idx, celda in enumerate(fila):
                celda_limpia = str(celda).strip().replace("\n", " ")
                if any(g in celda_limpia for g in ["1.°", "2.", "3.°", "4.°", "5.°"]):
                    if "1" in celda_limpia: grado = "1.°"
                    elif "2" in celda_limpia: grado = "2.°"
                    elif "3" in celda_limpia: grado = "3.°"
                    elif "4" in celda_limpia: grado = "4.°"
                    elif "5" in celda_limpia: grado = "5.°"
                    mapa_columnas[grado] = idx
            break

    # 4. Extracción y Limpieza de la Matriz de Notas
    area_actual = None
    registro_notas = []

    for fila in todas_las_filas:
        if not fila or len(fila) < 2:
            continue
            
        texto_fila = " ".join([str(c) for c in fila[:3] if c]).upper().replace("\n", "").replace(" ", "")
        if any(x in texto_fila for x in ["AÑOLECTIVO", "GRADO:", "CÓDIGOMODULAR", "CODIGOMODULAR", "SITUACIÓNFINAL"]):
            continue

        cambio_de_area = False
        for area in AREAS_OBJETIVO:
            area_sin_espacio = area.replace(" ", "")
            if area_sin_espacio in texto_fila:
                area_actual = area
                cambio_de_area = True
                break
        
        AREAS_EXCLUIDAS = ["INGLÉS", "INGLES", "RELIGIOSA", "QUECHUA", "CASTELLANO", "FÍSICA", "FISICA", "TRANSVERSALES", "TALLER"]
        if not cambio_de_area and any(x in texto_fila for x in AREAS_EXCLUIDAS):
            area_actual = "IGNORAR"

        if area_actual and area_actual != "IGNORAR":
            competencia = str(fila[1]).strip().split("\n")[0] if len(fila) > 1 and fila[1] else "Competencia"
            competencia_limpia = competencia.replace(" ", "").upper()
            
            if competencia_limpia in [a.replace(" ", "") for a in AREAS_OBJETIVO] or "NOTADEÁREA" in competencia_limpia or "PROMEDIO" in competencia_limpia:
                competencia = "Competencia / Nota General"

            diccionario_fila = {
                "Área Evaluada": area_actual,
                "Detalle / Competencia": competencia[:35]
            }
            
            for grado, col_idx in mapa_columnas.items():
                if col_idx < len(fila):
                    nota = str(fila[col_idx]).strip().replace("\n", "").upper()
                    diccionario_fila[grado] = nota if nota in ["A", "AD", "B", "C"] else "-"
                else:
                    diccionario_fila[grado] = "-"
                    
            registro_notas.append(diccionario_fila)

    df_notas = pd.DataFrame(registro_notas)
    return dni, nombre, mapa_columnas, df_notas

# =========================================================================
# LÓGICA DE EVALUACIÓN DE REQUISITOS (LITERALES - 90% MÍNIMO A/AD)
# =========================================================================
def evaluar_periodos_literales(df_notas, mapa_grados):
    periodos_definicion = [
        {"nombre": "1.° a 4.° de Secundaria", "grados": ["1.°", "2.°", "3.°", "4.°"]},
        {"nombre": "1.° a 5.° de Secundaria", "grados": ["1.°", "2.°", "3.°", "4.°", "5.°"]},
        {"nombre": "3.° a 5.° de Secundaria", "grados": ["3.°", "4.°", "5.°"]}
    ]
    
    resultados_periodos = []
    
    for p in periodos_definicion:
        grados_a_evaluar = [g for g in p["grados"] if g in mapa_grados]
        
        total_notas = 0
        notas_excelencia = 0  # Cantidad de calificativos 'A' o 'AD'
        
        if df_notas is not None and not df_notas.empty:
            for g in grados_a_evaluar:
                if g in df_notas.columns:
                    for nota in df_notas[g]:
                        if nota in ["A", "AD", "B", "C"]:
                            total_notas += 1
                            if nota in ["A", "AD"]:
                                notas_excelencia += 1
                                
        if total_notas > 0:
            porcentaje = round((notas_excelencia / total_notas) * 100, 2)
            estado = "CUMPLE" if porcentaje >= 90.0 else "NO CUMPLE"
        else:
            porcentaje = 0.0
            estado = "SIN NOTAS REGISTRADAS"
            
        resultados_periodos.append({
            "Periodo": p["nombre"],
            "Total Notas": total_notas,
            "Notas A o AD": notas_excelencia,
            "Porcentaje": f"{porcentaje}%",
            "ESTADO": estado,
            "_porcentaje_num": porcentaje
        })
        
    return pd.DataFrame(resultados_periodos)


def main():    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Renderizar título y diseño superior
    logo_path = os.path.join(current_dir, "logo-upch.png")
    logo_html = ""
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as image_file:
            encoded_logo = base64.b64encode(image_file.read()).decode()
            logo_html = f'<img src="data:image/png;base64,{encoded_logo}" width="80" style="margin-right: 20px;">'
            
    st.markdown(f"""
        <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 20px;">
            {logo_html}
            <h1 style="margin: 0; font-size: 2em; color: white;">Sistema de Evaluación de Notas - UPCH</h1>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("""
        <div style="text-align: justify; font-size: 1.2em; color: white;">
            <h2 style="font-size: 1.4em;"><strong>Modalidad FACTOR EXCELENCIA</strong></h2>
            <p>Este aplicativo determina si los postulantes son aptos para postular por la modalidad de admisión FACTOR EXCELENCIA en notas literales.</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Desplegables informativos de requisitos
    st.markdown("""<style> div[data-testid="stExpander"] summary {color: white;} </style>""", unsafe_allow_html=True)
    
    with st.expander("Ver Requisitos para Certificados / Constancias Literales (90% A o AD)"):
        st.markdown("""
        <div style="color: white;">
            <ul>
                <li>Aplica para postulantes con calificativos literales (A, AD, B, C).</li>
                <li>Deben registrar como mínimo el <strong>90% de sus notas con calificación A o AD</strong> en las áreas objetivo (Arte, Ciencia y Tec., Ciencias Sociales, Comunicación, Desarrollo Personal, EPT y Matemática).</li>
                <li>Se evalúa bajo 3 cortes: 1° a 4° grado, 1° a 5° grado o de 3° a 5° grado de secundaria.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    # Selección de carrera utilizando streamlit_option_menu
    carrera = option_menu(
        menu_title="Selecciona la carrera",
        options=["MEDICINA", "Todas las carreras, excepto MEDICINA"],
        icons=["activity", "book"],
        menu_icon="cast",
        default_index=0,
        orientation="horizontal"
    )
    
    # Carga de archivos
    st.markdown("""<style>[data-testid="stFileUploader"] label {color: white !important;} </style> """, unsafe_allow_html=True)
    files = st.file_uploader('Adjunta tu Certificado de Estudios COE o CLA (Formato PDF)', accept_multiple_files=True, type=['pdf'])
    
    if not files:
        return
        
    progress_bar = st.progress(0, text="Procesando archivos...")
    
    # Almacenamiento estructurado para navegación entre pestañas
    dict_estudiantes = {}
    errores_registro = []
    last_dni = None
    
    n = len(files)
    for i, file in enumerate(files):
        progress_bar.progress((i + 1) / n, f"Analizando documento {i + 1} de {n}...")
        try:
            file_bytes = file.read()
            dni, nombre, mapa_grados, df_notas = procesar_constancia_literal(file_bytes)
            df_periodos = evaluar_periodos_literales(df_notas, mapa_grados)
            
            dict_estudiantes[dni] = {
                "Nombre": nombre,
                "MatrizNotas": df_notas,
                "Periodos": df_periodos,
                "MapaGrados": mapa_grados
            }
            last_dni = dni
        except Exception as e:
            errores_registro.append({"Archivo": file.name, "Error": str(e)})
            continue

    progress_bar.empty()
    
    # Renderizado de Paneles y Resultados
    st.markdown("""<style> .stTabs [data-baseweb="tab"] {color: white !important;}</style> """, unsafe_allow_html=True)
    res, cal, tab, err = st.tabs(['Resultados', 'Cálculos Avanzados', 'Matriz de Notas', 'Errores de Lectura'])
    
    if dict_estudiantes:
        with res:
            dni_options = list(dict_estudiantes.keys())
            dni_seleccionado = st.selectbox("Filtrar por DNI del Estudiante:", options=dni_options, index=dni_options.index(last_dni) if last_dni in dni_options else 0)
            
            estudiante_actual = dict_estudiantes[dni_seleccionado]
            st.markdown(f"<h3 style='color:white;'>👤 Estudiante: <b>{estudiante_actual['Nombre']}</b></h3>",unsafe_allow_html=True)
            st.markdown(f"<p style='color:white;'>🪪 <b>DNI:</b> {dni_seleccionado}</p>",unsafe_allow_html=True)
            
            st.markdown( "<p style='color:white;'>📈 <b>Resultados de Auditoría por Periodo Académico:</b></p>",unsafe_allow_html=True)
            df_mostrar_periodos = estudiante_actual['Periodos'].drop(columns=['_porcentaje_num'])
            st.dataframe(df_mostrar_periodos, use_container_width=True)
            
            # Criterio de Aprobación: Si cumple en CUALQUIERA de los periodos válidos, se considera Apto.
            aplica = (estudiante_actual['Periodos']['ESTADO'] == 'CUMPLE').any()
            if aplica:
                st.success("🎉 El estudiante APLICA y es APTO para la modalidad Factor Excelencia.")
            else:
                st.error("❌ El estudiante NO APLICA para esta modalidad de admisión (No alcanza el 90% mínimo de notas A o AD).")
            
            # Exportador a Excel unificado
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                summary_data = []
                for k, v in dict_estudiantes.items():
                    mejor_periodo = v['Periodos'].loc[v['Periodos']['_porcentaje_num'].idxmax()]
                    summary_data.append({
                        "DNI": k,
                        "Nombre": v['Nombre'],
                        "Periodo Óptimo": mejor_periodo['Periodo'],
                        "Porcentaje Máximo": mejor_periodo['Porcentaje'],
                        "Condición Final": "APTO" if (v['Periodos']['ESTADO'] == 'CUMPLE').any() else "NO APTO"
                    })
                pd.DataFrame(summary_data).to_excel(writer, index=False, sheet_name="Resumen")
            st.download_button("📥 Descargar Reporte Consolidado (.xlsx)", data=buffer.getvalue(), file_name="Resultado_Evaluacion.xlsx", mime="application/vnd.ms-excel")
            
        with cal:
            st.markdown("### 📊 Conteo de Calificativos de Excelencia")
            df_notas_est = estudiante_actual['MatrizNotas']
            grados_detectados = list(estudiante_actual['MapaGrados'].keys())
            
            conteo_lista = []
            for g in grados_detectados:
                if g in df_notas_est.columns:
                    counts = df_notas_est[g].value_count_reindex = df_notas_est[g].value_counts()
                    conteo_lista.append({
                        "Grado": g,
                        "Cant. AD": counts.get("AD", 0),
                        "Cant. A": counts.get("A", 0),
                        "Cant. B": counts.get("B", 0),
                        "Cant. C": counts.get("C", 0),
                    })
            st.dataframe(pd.DataFrame(conteo_lista).set_index("Grado"), use_container_width=True)

        with tab:
            st.markdown("### 📋 Matriz de Notas Extraída del SIAGIE")
            st.dataframe(estudiante_actual['MatrizNotas'], use_container_width=True)
            
    with err:
        df_errs = pd.DataFrame(errores_registro)
        if df_errs.empty:
            st.write("✅ No se registraron errores durante la carga de expedientes.")
        else:
            st.dataframe(df_errs, use_container_width=True)
            st.error(f"¡Atención! Se detectaron {len(errores_registro)} archivos con problemas de lectura.")

if __name__ == '__main__':
    main()