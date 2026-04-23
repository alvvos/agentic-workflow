import pandas as pd
import numpy as np
import ast

def generar_excel_embudos(df_filt, writer, workbook):
    # Conservamos exactamente los mismos colores y formatos que definiste
    fmt_h_uni = workbook.add_format({'bold': True, 'bg_color': '#375623', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_h_pct = workbook.add_format({'bold': True, 'bg_color': '#C65911', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_h_hora = workbook.add_format({'bold': True, 'bg_color': '#203764', 'font_color': 'white', 'border': 1, 'align': 'center'})
    
    fmt_int = workbook.add_format({'num_format': '#,##0', 'align': 'center', 'border': 1})
    fmt_pct = workbook.add_format({'num_format': '0.0%', 'align': 'center', 'border': 1})
    fmt_date = workbook.add_format({'num_format': 'yyyy-mm-dd', 'align': 'center', 'border': 1})
    fmt_str = workbook.add_format({'align': 'center', 'border': 1})

    def safely_eval_hours(x):
        try:
            if isinstance(x, str): return ast.literal_eval(x)
            if isinstance(x, list): return x
        except: pass
        return [0]*24

    # 1. Preparación para las agrupaciones condicionales
    df_filt = df_filt.copy()
    df_filt['fecha'] = pd.to_datetime(df_filt['fecha'])
    dias_periodo = (df_filt['fecha'].max() - df_filt['fecha'].min()).days
    mas_de_un_mes = dias_periodo > 31

    if mas_de_un_mes:
        # Formatos: Año-Mes (2024-05) y Año-Semana (2024-W15)
        df_filt['Mes'] = df_filt['fecha'].dt.strftime('%Y-%m')
        df_filt['Semana'] = df_filt['fecha'].dt.strftime('%Y-W%W') 

    for loc in df_filt['Ubicación'].unique():
        df_loc = df_filt[df_filt['Ubicación'] == loc]
        sheet_name = str(loc)[:31].replace(':', '').replace('/', '')
        
        orden_zonas = df_loc.groupby('Zona')['unique_visitors'].sum().sort_values(ascending=False).index.tolist()
        if not orden_zonas: continue
            
        df_fecha = df_loc.pivot_table(index='fecha', columns='Zona', values='unique_visitors', aggfunc='sum', observed=True).fillna(0).reset_index()
        
        # Agrupaciones condicionales si el periodo es > 1 mes
        if mas_de_un_mes:
            df_semana_cal = df_loc.pivot_table(index='Semana', columns='Zona', values='unique_visitors', aggfunc='sum', observed=True).fillna(0).reset_index()
            df_mes = df_loc.pivot_table(index='Mes', columns='Zona', values='unique_visitors', aggfunc='sum', observed=True).fillna(0).reset_index()
            
        df_semana = df_loc.pivot_table(index='Día semana', columns='Zona', values='unique_visitors', aggfunc='mean', observed=True).fillna(0).round(0).reset_index()
        
        horas_exp = pd.DataFrame(df_loc['hourly_visits'].apply(safely_eval_hours).to_list(), index=df_loc.index)
        horas_exp.columns = [f"{i:02d}:00" for i in range(24)]
        df_calor = pd.concat([df_loc[['Zona']], horas_exp], axis=1)
        df_hora = df_calor.groupby('Zona').mean().T.round(0).reset_index()
        df_hora.rename(columns={'index': 'Hora'}, inplace=True)
        
        ws = workbook.add_worksheet(sheet_name)
        writer.sheets[sheet_name] = ws
        ws.set_column('A:A', 16, fmt_str)
        
        fila_actual = 1
        
        def escribir_tabla_embudo(df_datos, titulo, fila_inicio, fmt_cabecera, col_indice):
            ws.write(fila_inicio-1, 0, titulo, workbook.add_format({'bold': True, 'size': 12}))
            
            columnas_finales = [col_indice]
            for i in range(len(orden_zonas)):
                z_act = orden_zonas[i]
                if z_act in df_datos.columns:
                    columnas_finales.append(z_act)
                    if i < len(orden_zonas) - 1:
                        z_sig = orden_zonas[i+1]
                        if z_sig in df_datos.columns:
                            col_pct = f"» % a {z_sig}" 
                            df_datos[col_pct] = np.where(df_datos[z_act] > 0, df_datos[z_sig] / df_datos[z_act], 0)
                            columnas_finales.append(col_pct)
            
            df_final = df_datos[[c for c in columnas_finales if c in df_datos.columns]]
            
            for c_idx, col in enumerate(df_final.columns):
                fmt = fmt_h_pct if '»' in col else fmt_cabecera
                ws.write(fila_inicio, c_idx, col, fmt)
            
            for r_idx, r in df_final.iterrows():
                val_idx = r.iloc[0]
                fmt_idx = fmt_date if col_indice == 'fecha' else fmt_str
                ws.write(fila_inicio + 1 + r_idx, 0, val_idx, fmt_idx) 
                
                for c_idx, col in enumerate(df_final.columns[1:], 1):
                    val = r.iloc[c_idx]
                    if '»' in col: ws.write(fila_inicio + 1 + r_idx, c_idx, val, fmt_pct)
                    else: ws.write(fila_inicio + 1 + r_idx, c_idx, val, fmt_int)
                        
            for c_idx, col in enumerate(df_final.columns[1:], 1):
                if '»' in col:
                    ws.set_column(c_idx, c_idx, 16)
                    ws.conditional_format(fila_inicio+1, c_idx, fila_inicio+len(df_final), c_idx, {'type': '2_color_scale', 'min_color': "#F8696B", 'max_color': "#63BE7B"})
                else:
                    ws.set_column(c_idx, c_idx, 20)
                    if fmt_cabecera == fmt_h_hora: 
                        ws.conditional_format(fila_inicio+1, c_idx, fila_inicio+len(df_final), c_idx, {'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#FFE082", 'max_color': "#F44336"})
                    else: 
                        ws.conditional_format(fila_inicio+1, c_idx, fila_inicio+len(df_final), c_idx, {'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#C6E0B4", 'max_color': "#548235"})
            
            return fila_inicio + len(df_final) + 4
        
        # 2. Imprimimos las tablas en cascada
        fila_actual = escribir_tabla_embudo(df_fecha, "EMBUDO POR FECHAS (Visitantes Diarios)", fila_actual, fmt_h_uni, 'fecha')
        
        if mas_de_un_mes:
            fila_actual = escribir_tabla_embudo(df_semana_cal, "EMBUDO POR SEMANAS (Visitantes Totales)", fila_actual, fmt_h_uni, 'Semana')
            fila_actual = escribir_tabla_embudo(df_mes, "EMBUDO POR MESES (Visitantes Totales)", fila_actual, fmt_h_uni, 'Mes')
            
        fila_actual = escribir_tabla_embudo(df_semana, "EMBUDO POR DÍA DE LA SEMANA (Media de Visitantes)", fila_actual, fmt_h_uni, 'Día semana')
        fila_actual = escribir_tabla_embudo(df_hora, "EMBUDO POR HORA (Media de Visitas Totales)", fila_actual, fmt_h_hora, 'Hora')