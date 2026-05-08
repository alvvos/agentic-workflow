import io
import ast
import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.chart.data import CategoryChartData
import calendar

# Paleta de colores base (Tema Oscuro)
C_BG = RGBColor(10, 15, 26)      
C_ACCENT = RGBColor(0, 242, 255) 
C_TEXT = RGBColor(248, 250, 252) 
C_DIM = RGBColor(148, 163, 184)  
C_GREEN = RGBColor(16, 185, 129)

def aplicar_fondo_oscuro(slide):
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = C_BG

def parsear_array_horas(val):
    try:
        return ast.literal_eval(val) if isinstance(val, str) else val
    except:
        return [0]*24

def agregar_grafico_barras(slide, x, y, cx, cy, categorias, valores, titulo):
    chart_data = CategoryChartData()
    chart_data.categories = categorias
    chart_data.add_series('Visitas', valores)
    
    chart = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, x, y, cx, cy, chart_data
    ).chart
    
    chart.has_legend = False
    chart.chart_title.has_text_frame = True
    chart.chart_title.text_frame.text = titulo
    chart.chart_title.text_frame.paragraphs[0].font.size = Pt(12)
    chart.chart_title.text_frame.paragraphs[0].font.color.rgb = C_DIM

def generar_reporte_pptx(df, stream, start_date, end_date):
    prs = Presentation()
    slide_layout = prs.slide_layouts[6] # Blank layout

    # 1. PREPARACIÓN DE DATOS MAESTROS
    df_clean = df.copy()
    df_clean['Mes'] = df_clean['fecha'].dt.month
    df_clean['NombreMes'] = df_clean['fecha'].dt.month.apply(lambda x: calendar.month_name[x].capitalize() if pd.notnull(x) else "Desconocido")
    
    # Extraer arrays horarios para sumarizarlos
    df_clean['hourly_array'] = df_clean['hourly_visits'].apply(parsear_array_horas)

    # --- DIAPOSITIVA 1: PORTADA ---
    slide_portada = prs.slides.add_slide(slide_layout)
    aplicar_fondo_oscuro(slide_portada)
    
    txBox = slide_portada.shapes.add_textbox(Inches(1), Inches(2.5), Inches(8), Inches(2))
    tf = txBox.text_frame
    p = tf.add_paragraph()
    p.text = "Informe Operativo Retail Consolidado"
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = C_ACCENT

    p2 = tf.add_paragraph()
    p2.text = f"Análisis de flujo: {start_date.strftime('%d/%m/%Y')} al {end_date.strftime('%d/%m/%Y')}"
    p2.font.size = Pt(18)
    p2.font.color.rgb = C_DIM

    # --- DIAPOSITIVA 2: VISIÓN GLOBAL CONSOLIDADA ---
    slide_global = prs.slides.add_slide(slide_layout)
    aplicar_fondo_oscuro(slide_global)
    
    # Título Global
    tb_g = slide_global.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
    tb_g.text_frame.text = "Visión Global Consolidada"
    tb_g.text_frame.paragraphs[0].font.size = Pt(28)
    tb_g.text_frame.paragraphs[0].font.color.rgb = C_ACCENT
    tb_g.text_frame.paragraphs[0].font.bold = True

    # Tabla Total por Zonas
    resumen_global = df_clean.groupby('Zona')['total_visits'].sum().reset_index()
    filas = len(resumen_global) + 1
    tabla_global = slide_global.shapes.add_table(filas, 2, Inches(0.5), Inches(1.2), Inches(4), Inches(0.4 * filas)).table
    
    tabla_global.cell(0,0).text = "Zona Analítica"
    tabla_global.cell(0,1).text = "Volumen Total"
    
    for i, row in resumen_global.iterrows():
        tabla_global.cell(i+1, 0).text = str(row['Zona'])
        tabla_global.cell(i+1, 1).text = f"{int(row['total_visits']):,}".replace(',', '.')
        for c in [0, 1]:
            tabla_global.cell(i+1, c).text_frame.paragraphs[0].font.color.rgb = C_TEXT

    # Gráfico Global de Horas
    horas_totales = [0]*24
    for arr in df_clean['hourly_array']:
        if isinstance(arr, list) and len(arr) == 24:
            horas_totales = [a + b for a, b in zip(horas_totales, arr)]
            
    categorias_horas = [f"{h:02d}:00" for h in range(24)]
    agregar_grafico_barras(slide_global, Inches(4.8), Inches(1.2), Inches(4.8), Inches(3.5), 
                           categorias_horas, horas_totales, "Intensidad Horaria Consolidada")

    # --- DIAPOSITIVAS MENSUALES (BUCLE) ---
    meses = df_clean['Mes'].dropna().unique()
    meses.sort()

    for mes in meses:
        df_mes = df_clean[df_clean['Mes'] == mes]
        nombre_mes = df_mes['NombreMes'].iloc[0]
        
        slide_mes = prs.slides.add_slide(slide_layout)
        aplicar_fondo_oscuro(slide_mes)
        
        # Título Mensual
        tb_m = slide_mes.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
        tb_m.text_frame.text = f"Análisis Granular: {nombre_mes}"
        tb_m.text_frame.paragraphs[0].font.size = Pt(28)
        tb_m.text_frame.paragraphs[0].font.color.rgb = C_GREEN
        tb_m.text_frame.paragraphs[0].font.bold = True

        # Tabla Zonas Mes
        resumen_mes = df_mes.groupby('Zona')['total_visits'].sum().reset_index()
        filas_m = len(resumen_mes) + 1
        tabla_mes = slide_mes.shapes.add_table(filas_m, 2, Inches(0.5), Inches(1.2), Inches(3.5), Inches(0.4 * filas_m)).table
        tabla_mes.cell(0,0).text = "Zona"
        tabla_mes.cell(0,1).text = "Visitas"
        for i, row in resumen_mes.iterrows():
            tabla_mes.cell(i+1, 0).text = str(row['Zona'])
            tabla_mes.cell(i+1, 1).text = f"{int(row['total_visits']):,}".replace(',', '.')
            for c in [0, 1]: tabla_mes.cell(i+1, c).text_frame.paragraphs[0].font.color.rgb = C_TEXT

        # Gráfico: Tendencia Semanal del Mes
        if 'Semana del periodo' in df_mes.columns:
            semanas_mes = df_mes.groupby('Semana del periodo')['total_visits'].sum().reset_index()
            agregar_grafico_barras(slide_mes, Inches(4.2), Inches(1.2), Inches(5.5), Inches(2.5), 
                                   semanas_mes['Semana del periodo'].tolist(), 
                                   semanas_mes['total_visits'].tolist(), 
                                   "Tendencia por Semanas")

        # Gráfico: Horario del Mes
        horas_mes = [0]*24
        for arr in df_mes['hourly_array']:
            if isinstance(arr, list) and len(arr) == 24:
                horas_mes = [a + b for a, b in zip(horas_mes, arr)]
                
        agregar_grafico_barras(slide_mes, Inches(0.5), Inches(4.0), Inches(9.2), Inches(3.0), 
                               categorias_horas, horas_mes, "Distribución Horaria del Mes")

    # 3. GUARDAR RESULTADO EN MEMORIA
    prs.save(stream)