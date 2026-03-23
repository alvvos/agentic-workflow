import pandas as pd
import ast

def generar_excel_operativo(df_filt, writer, workbook, kpis_oficiales=None):
    if kpis_oficiales is None: kpis_oficiales = []
    
    fmt_h = workbook.add_format({'bold': True, 'bg_color': '#203764', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_h_zona = workbook.add_format({'bold': True, 'bg_color': '#C6E0B4', 'font_color': 'black', 'border': 1, 'align': 'left'})
    fmt_h_zona_dwell = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'font_color': 'black', 'border': 1, 'align': 'left'})
    fmt_int = workbook.add_format({'num_format': '#,##0', 'align': 'center', 'border': 1})
    fmt_float = workbook.add_format({'num_format': '0.0', 'align': 'center', 'border': 1})
    
    fmt_kpi_h = workbook.add_format({'bold': True, 'bg_color': '#FFC000', 'font_color': 'black', 'border': 1, 'align': 'center', 'size': 12})
    fmt_kpi_val = workbook.add_format({'bold': True, 'font_color': '#C65911', 'border': 1, 'align': 'center', 'size': 13, 'num_format': '#,##0'})
    
    mapa_cols_kpi = {
        "7d": ("Visitantes (Últ. 7 días)", "uv_7d"),
        "28d": ("Visitantes (Últ. 28 días)", "uv_28d"),
        "month": ("Visitantes (Mes actual)", "uv_month"),
        "year": ("Visitantes (Año actual)", "uv_year")
    }
    
    def safely_eval_hours(x):
        try:
            if isinstance(x, str): return ast.literal_eval(x)
            if isinstance(x, list): return x
        except: pass
        return [0]*24

    for loc in df_filt['Ubicación'].unique():
        df_loc = df_filt[df_filt['Ubicación'] == loc]
        sheet_name = str(loc)[:31].replace(':', '').replace('/', '')
        
        start_row = 1
        
        # =========================================================
        # 0. TARJETA DE KPIs OFICIALES
        # =========================================================
        if kpis_oficiales:
            ws = workbook.add_worksheet(sheet_name)
            writer.sheets[sheet_name] = ws
            
            ultima_fecha = df_loc['fecha'].max()
            df_ultimo_dia = df_loc[df_loc['fecha'] == ultima_fecha]
            
            ws.write(0, 0, f"KPIs OFICIALES DE LA PLATAFORMA (Datos consolidados a fecha {ultima_fecha.strftime('%d-%m-%Y')})", workbook.add_format({'bold': True, 'size': 13, 'font_color': '#C65911'}))
            
            ws.write(1, 0, "Zona", fmt_kpi_h)
            for idx, kpi_key in enumerate(kpis_oficiales):
                ws.write(1, 1 + idx, mapa_cols_kpi[kpi_key][0], fmt_kpi_h)
                ws.set_column(1 + idx, 1 + idx, 22)
            
            fila_kpi = 2
            for _, row in df_ultimo_dia.iterrows():
                ws.write(fila_kpi, 0, row['Zona'], fmt_h)
                for idx, kpi_key in enumerate(kpis_oficiales):
                    col_db = mapa_cols_kpi[kpi_key][1]
                    valor = row[col_db] if col_db in row.index else 0
                    ws.write(fila_kpi, 1 + idx, valor, fmt_kpi_val)
                fila_kpi += 1
            
            start_row = fila_kpi + 2
        
        # =========================================================
        # 1. PIVOT POR DÍA DE LA SEMANA (Visitas totales desglosadas)
        # =========================================================
        df_day = df_loc.pivot_table(index='Día semana', columns='Zona', values='total_visits', aggfunc='mean', observed=True).fillna(0).round(0)
        df_day.reset_index(inplace=True)
        
        if start_row == 1:
            df_day.to_excel(writer, sheet_name=sheet_name, startrow=start_row, index=False)
            ws = writer.sheets[sheet_name]
        else:
            for j, c in enumerate(df_day.columns): ws.write(start_row, j, c, fmt_h)
            for r_idx, r in df_day.iterrows():
                for c_idx, val in enumerate(r): ws.write(start_row + 1 + r_idx, c_idx, val)

        ws.write(start_row-1, 0, f"Visitas medias por Día (Período analizado)", workbook.add_format({'bold': True, 'size': 12}))
        ws.set_column('A:A', 18, fmt_int)
        
        for i, col in enumerate(df_day.columns):
            ws.write(start_row, i, col, fmt_h)
            if i > 0:
                ws.set_column(i, i, 16, fmt_int)
                ws.conditional_format(start_row+1, i, start_row+1+len(df_day), i, {'type': 'data_bar', 'bar_color': '#D9E1F2'})

        # PLOT: Volumen Total (Barras)
        chart_day = workbook.add_chart({'type': 'column'})
        for i in range(1, len(df_day.columns)):
            chart_day.add_series({
                'name': [sheet_name, start_row, i],
                'categories': [sheet_name, start_row+1, 0, start_row+len(df_day), 0],
                'values': [sheet_name, start_row+1, i, start_row+len(df_day), i]
            })
        chart_day.set_title({'name': 'Volumen medio por día', 'name_font': {'size': 11}})
        chart_day.set_size({'width': 480, 'height': 250})
        ws.insert_chart(f'J{start_row+1}', chart_day)

        # =========================================================
        # 2. TABLAS SEPARADAS: VISITANTES POR ZONA (Diarios)
        # =========================================================
        start_u = start_row + len(df_day) + 3
        ws.write(start_u, 0, "Mapas de Calor: Visitantes (No sumar)", workbook.add_format({'bold': True, 'size': 12, 'font_color': '#375623'}))
        start_u += 2
        
        zonas_loc = df_loc['Zona'].unique()
        
        for zona in zonas_loc:
            df_z = df_loc[df_loc['Zona'] == zona]
            df_cal_unicos = df_z.pivot_table(index='Semana del periodo', columns='Día semana', values='unique_visitors', aggfunc='mean', observed=True).fillna(0).round(0).reset_index()
            
            ws.write(start_u, 0, f"Zona: {zona} (Visitantes)", fmt_h_zona)
            
            for j, c in enumerate(df_cal_unicos.columns): ws.write(start_u+1, j, c, fmt_h)
            for r_idx, r in df_cal_unicos.iterrows():
                for c_idx, val in enumerate(r): ws.write(start_u + 2 + r_idx, c_idx, val, fmt_int)
            
            for i, col in enumerate(df_cal_unicos.columns):
                if i == 0: ws.set_column(i, i, 20, fmt_int)
                else:
                    ws.conditional_format(start_u+2, i, start_u+1+len(df_cal_unicos), i, {
                        'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#C6E0B4", 'max_color': "#548235"
                    })
            
            # PLOT: Visitantes para esta Zona (Líneas)
            chart_u = workbook.add_chart({'type': 'line'})
            for r_idx in range(len(df_cal_unicos)):
                chart_u.add_series({
                    'name': [sheet_name, start_u + 2 + r_idx, 0],
                    'categories': [sheet_name, start_u + 1, 1, start_u + 1, len(df_cal_unicos.columns) - 1],
                    'values': [sheet_name, start_u + 2 + r_idx, 1, start_u + 2 + r_idx, len(df_cal_unicos.columns) - 1],
                    'marker': {'type': 'circle', 'size': 5}
                })
            chart_u.set_title({'name': f'Tendencia Visitantes - {zona}', 'name_font': {'size': 10}})
            chart_u.set_size({'width': 480, 'height': 220})
            ws.insert_chart(f'J{start_u+1}', chart_u)
            
            start_u += max(len(df_cal_unicos) + 4, 12) # Espaciado mínimo para que quepan los gráficos sin solaparse

        # =========================================================
        # 3. TABLAS SEPARADAS: TIEMPO DE ESTANCIA POR ZONA
        # =========================================================
        start_d = start_u
        ws.write(start_d, 0, "Mapas de Calor: Tiempo de Estancia en Minutos", workbook.add_format({'bold': True, 'size': 12, 'font_color': '#2F75B5'}))
        start_d += 2
        
        for zona in zonas_loc:
            df_z = df_loc[df_loc['Zona'] == zona]
            df_cal_dwell = df_z.pivot_table(index='Semana del periodo', columns='Día semana', values='dwell_time', aggfunc='mean', observed=True).fillna(0).round(1).reset_index()
            
            ws.write(start_d, 0, f"Zona: {zona} (Minutos)", fmt_h_zona_dwell)
            
            for j, c in enumerate(df_cal_dwell.columns): ws.write(start_d+1, j, c, fmt_h)
            for r_idx, r in df_cal_dwell.iterrows():
                for c_idx, val in enumerate(r): 
                    fmt = fmt_int if c_idx == 0 else fmt_float
                    ws.write(start_d + 2 + r_idx, c_idx, val, fmt)
            
            for i, col in enumerate(df_cal_dwell.columns):
                if i > 0:
                    ws.conditional_format(start_d+2, i, start_d+1+len(df_cal_dwell), i, {
                        'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#9BC2E6", 'max_color': "#2F75B5"
                    })
            
            # PLOT: Tiempo de Estancia para esta Zona (Líneas)
            chart_d = workbook.add_chart({'type': 'line'})
            for r_idx in range(len(df_cal_dwell)):
                chart_d.add_series({
                    'name': [sheet_name, start_d + 2 + r_idx, 0],
                    'categories': [sheet_name, start_d + 1, 1, start_d + 1, len(df_cal_dwell.columns) - 1],
                    'values': [sheet_name, start_d + 2 + r_idx, 1, start_d + 2 + r_idx, len(df_cal_dwell.columns) - 1],
                    'marker': {'type': 'circle', 'size': 5}
                })
            chart_d.set_title({'name': f'Tendencia Estancia - {zona}', 'name_font': {'size': 10}})
            chart_d.set_size({'width': 480, 'height': 220})
            ws.insert_chart(f'J{start_d+1}', chart_d)
            
            start_d += max(len(df_cal_dwell) + 4, 12)

        # =========================================================
        # 4. PIVOT POR HORA DEL DÍA (Mapa de calor de afluencia)
        # =========================================================
        horas_exp = pd.DataFrame(df_loc['hourly_visits'].apply(safely_eval_hours).to_list(), index=df_loc.index)
        horas_exp.columns = [f"{i:02d}:00" for i in range(24)]
        df_calor = pd.concat([df_loc[['Zona']], horas_exp], axis=1)
        
        df_hour = df_calor.groupby('Zona').mean().T.round(0).reset_index()
        df_hour.rename(columns={'index': 'Hora'}, inplace=True)
        
        start_h = start_d + 1
        ws.write(start_h, 0, "Tráfico medio por Hora", workbook.add_format({'bold': True, 'size': 12}))
        
        for j, c in enumerate(df_hour.columns): ws.write(start_h+1, j, c, fmt_h)
        for r_idx, r in df_hour.iterrows():
            for c_idx, val in enumerate(r): ws.write(start_h + 2 + r_idx, c_idx, val, fmt_int)

        for i, col in enumerate(df_hour.columns):
            if i > 0:
                ws.conditional_format(start_h+2, i, start_h+1+len(df_hour), i, {
                    'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#FFE082", 'max_color': "#F44336"
                })

        # PLOT: Curva Horaria (Líneas)
        chart_h = workbook.add_chart({'type': 'line'})
        for i in range(1, len(df_hour.columns)):
            chart_h.add_series({
                'name': [sheet_name, start_h+1, i],
                'categories': [sheet_name, start_h+2, 0, start_h+1+len(df_hour), 0],
                'values': [sheet_name, start_h+2, i, start_h+1+len(df_hour), i],
                'line': {'width': 2.2}
            })
        chart_h.set_title({'name': 'Curva de afluencia horaria', 'name_font': {'size': 11}})
        chart_h.set_size({'width': 800, 'height': 380})
        ws.insert_chart(f'J{start_h+1}', chart_h)