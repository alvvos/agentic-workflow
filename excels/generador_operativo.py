import pandas as pd
import ast
from datetime import datetime

def safely_eval_hours(x):
    try:
        if isinstance(x, str): return ast.literal_eval(x)
        if isinstance(x, list): return x
    except: pass
    return [0]*24

def safely_eval_dwell_dict(x):
    try:
        if isinstance(x, str): return ast.literal_eval(x)
        if isinstance(x, dict): return x
    except: pass
    return {}

def ordenar_zonas(zonas):
    def peso(z):
        zl = str(z).lower()
        if 'exterior' in zl or 'calle' in zl: return 1
        if 'tienda' in zl: return 2
        if 'caja' in zl: return 3
        return 4
    return sorted(zonas, key=peso)

def generar_excel_operativo(df_filt, writer, workbook, kpis_oficiales):
    fmt_title = workbook.add_format({'bold': True, 'size': 12, 'font_color': '#203764'})
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#203764', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_int = workbook.add_format({'num_format': '#,##0', 'align': 'center', 'border': 1})
    fmt_float = workbook.add_format({'num_format': '0.0', 'align': 'center', 'border': 1})
    
    orden_dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    meses_es = {1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio', 
                7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'}
    
    hoy = datetime.today()
    
    for loc in df_filt['Ubicación'].unique():
        df_loc = df_filt[df_filt['Ubicación'] == loc].copy()
        sheet_name = str(loc)[:31].replace(':', '').replace('/', '')
        ws = workbook.add_worksheet(sheet_name)
        writer.sheets[sheet_name] = ws
        
        ws.set_column('A:A', 25)
        ws.set_column('B:AE', 18)
        
        mostrar_mensual = False
        
        if 'fecha' in df_loc.columns:
            df_loc['fecha_dt'] = pd.to_datetime(df_loc['fecha'])
            
            df_loc['Mes_Año'] = df_loc['fecha_dt'].apply(lambda f: f"{meses_es.get(f.month, str(f.month))} {f.year}")
            df_loc['Semana_Mes'] = df_loc['fecha_dt'].apply(lambda f: f"Semana {(f.day - 1) // 7 + 1} de {meses_es.get(f.month, str(f.month))} {f.year}")
            
            meses_ordenados = df_loc[['fecha_dt', 'Mes_Año']].sort_values('fecha_dt')['Mes_Año'].unique()
            df_loc['Mes_Año'] = pd.Categorical(df_loc['Mes_Año'], categories=meses_ordenados, ordered=True)
            
            semanas_ordenadas = df_loc[['fecha_dt', 'Semana_Mes']].sort_values('fecha_dt')['Semana_Mes'].unique()
            df_loc['Semana_Mes'] = pd.Categorical(df_loc['Semana_Mes'], categories=semanas_ordenadas, ordered=True)
            
            mostrar_mensual = len(meses_ordenados) > 1
        else:
            df_loc['Mes_Año'] = "Periodo general"
            df_loc['Semana_Mes'] = "Periodo general"
            
        zonas_ordenadas = ordenar_zonas(df_loc['Zona'].unique())
        
        fila = 0
        
        ws.write(fila, 0, f"KPIs oficiales consolidados a fecha {hoy.strftime('%d-%m-%Y')}", fmt_title)
        fila += 1
        
        kpi_cols = ['Zona']
        if '7d' in kpis_oficiales:
            kpi_cols += ['Visitantes ultimos 7 dias', 'Frecuencia ultimos 7 dias']
        if '28d' in kpis_oficiales:
            kpi_cols += ['Visitantes ultimos 28 dias', 'Frecuencia ultimos 28 dias']
        if 'month' in kpis_oficiales:
            kpi_cols += ['Visitantes mes en curso', 'Frecuencia mes en curso']
        if 'year' in kpis_oficiales:
            kpi_cols += ['Visitantes año en curso', 'Frecuencia año en curso']
            
        for c_idx, col_name in enumerate(kpi_cols):
            ws.write(fila, c_idx, col_name, fmt_header)
        fila += 1
        
        for z in zonas_ordenadas:
            df_z = df_loc[df_loc['Zona'] == z].copy()
            row_data = [z]
            
            for col in kpi_cols[1:]:
                val = ''
                col_buscar = None
                
                if '7 dias' in col:
                    col_buscar = 'uv_7d' if 'Visitantes' in col else 'freq_7d'
                elif '28 dias' in col:
                    col_buscar = 'uv_28d' if 'Visitantes' in col else 'freq_28d'
                elif 'mes' in col.lower():
                    col_buscar = 'uv_month' if 'Visitantes' in col else 'freq_month'
                elif 'año' in col.lower():
                    col_buscar = 'uv_year' if 'Visitantes' in col else 'freq_year'
                
                if col_buscar and col_buscar in df_z.columns:
                    serie_limpia = df_z[col_buscar].dropna()
                    if not serie_limpia.empty:
                        val = serie_limpia.iloc[-1]
                            
                row_data.append(val)
                
            for c_idx, val in enumerate(row_data):
                fmt = fmt_float if isinstance(val, float) else fmt_int
                ws.write(fila, c_idx, val, fmt)
            fila += 1
            
        fila += 2
        
        ws.write(fila, 0, "Visitas totales medias por dia", fmt_title)
        fila += 1
        
        df_dia = df_loc.pivot_table(index='Día semana', columns='Zona', values='total_visits', aggfunc='mean', observed=True)
        df_dia = df_dia.reindex(orden_dias).fillna(0)
        df_dia = df_dia.reindex(columns=[z for z in zonas_ordenadas if z in df_dia.columns])
        
        ws.write(fila, 0, "Dia semana", fmt_header)
        for c_idx, z in enumerate(df_dia.columns):
            ws.write(fila, c_idx + 1, z, fmt_header)
        fila += 1
        
        fila_inicio_dia = fila
        for r_idx, (dia, row_data) in enumerate(df_dia.iterrows()):
            ws.write(fila, 0, dia, fmt_header)
            for c_idx, val in enumerate(row_data):
                ws.write(fila, c_idx + 1, val, fmt_int)
            fila += 1
            
        col_calle = [i for i, z in enumerate(df_dia.columns) if 'calle' in str(z).lower() or 'exterior' in str(z).lower()]
        col_int = [i for i, z in enumerate(df_dia.columns) if 'calle' not in str(z).lower() and 'exterior' not in str(z).lower()]
        
        offset_chart_row = fila_inicio_dia - 1
        
        if col_int:
            chart_int = workbook.add_chart({'type': 'column'})
            for i in col_int:
                chart_int.add_series({
                    'name': [sheet_name, fila_inicio_dia - 1, i + 1],
                    'categories': [sheet_name, fila_inicio_dia, 0, fila_inicio_dia + 6, 0],
                    'values': [sheet_name, fila_inicio_dia, i + 1, fila_inicio_dia + 6, i + 1],
                })
            chart_int.set_title({'name': 'Visitas totales medias por dia interior', 'name_font': {'size': 14}})
            chart_int.set_size({'width': 1200, 'height': 350})
            ws.insert_chart(offset_chart_row, len(df_dia.columns) + 2, chart_int)
            offset_chart_row += 20
            
        if col_calle:
            chart_ext = workbook.add_chart({'type': 'column'})
            for i in col_calle:
                chart_ext.add_series({
                    'name': [sheet_name, fila_inicio_dia - 1, i + 1],
                    'categories': [sheet_name, fila_inicio_dia, 0, fila_inicio_dia + 6, 0],
                    'values': [sheet_name, fila_inicio_dia, i + 1, fila_inicio_dia + 6, i + 1],
                })
            chart_ext.set_title({'name': 'Visitas totales medias por dia exterior', 'name_font': {'size': 14}})
            chart_ext.set_size({'width': 1200, 'height': 350})
            ws.insert_chart(offset_chart_row, len(df_dia.columns) + 2, chart_ext)
            
        fila = max(fila + 3, offset_chart_row + 20)
        
        ws.write(fila, 0, "Mapas de calor captacion y calidad diaria", fmt_title)
        fila += 2
        
        def dibujar_mapa(df_mapa, titulo, fila_actual, tipo_val, color_scale, chart_type='line'):
            ws.write(fila_actual, 0, titulo, fmt_title)
            fila_actual += 1
            
            df_mapa = df_mapa.reindex(columns=orden_dias).fillna(0)
            df_mapa['Promedio periodo'] = df_mapa.mean(axis=1)
            
            headers = ['Periodo'] + list(df_mapa.columns)
            for c_idx, h in enumerate(headers):
                ws.write(fila_actual, c_idx, h, fmt_header)
            fila_actual += 1
            
            fila_inicio_mapa = fila_actual
            for r_idx, (sem, row_data) in enumerate(df_mapa.iterrows()):
                ws.write(fila_actual, 0, sem, fmt_header)
                for c_idx, val in enumerate(row_data):
                    fmt = fmt_float if tipo_val == 'float' else fmt_int
                    ws.write(fila_actual, c_idx + 1, val, fmt)
                fila_actual += 1
                
            num_cols_dias = len(orden_dias)
            ws.conditional_format(fila_inicio_mapa, 1, fila_actual - 1, num_cols_dias, {
                'type': '3_color_scale', 'min_color': color_scale[0], 'mid_color': color_scale[1], 'max_color': color_scale[2]
            })
            ws.conditional_format(fila_inicio_mapa, num_cols_dias + 1, fila_actual - 1, num_cols_dias + 1, {
                'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#D9D9D9", 'max_color': "#808080"
            })
            
            chart = workbook.add_chart({'type': chart_type})

            for r_idx in range(len(df_mapa)):
                chart.add_series({
                    'name': [sheet_name, fila_inicio_mapa + r_idx, 0],
                    'categories': [sheet_name, fila_inicio_mapa - 1, 1, fila_inicio_mapa - 1, num_cols_dias],
                    'values': [sheet_name, fila_inicio_mapa + r_idx, 1, fila_inicio_mapa + r_idx, num_cols_dias],
                })
            chart.set_title({'name': titulo, 'name_font': {'size': 14}})
            chart.set_size({'width': 1200, 'height': 350})
            ws.insert_chart(fila_inicio_mapa - 1, len(df_mapa.columns) + 2, chart)
            
            return max(fila_actual + 2, fila_inicio_mapa + 20)

        for z in zonas_ordenadas:
            df_z = df_loc[df_loc['Zona'] == z]
            
            if 'total_visits' in df_z.columns:
                if mostrar_mensual:
                    df_tot_mes = df_z.pivot_table(index='Mes_Año', columns='Día semana', values='total_visits', aggfunc='sum', observed=True).dropna(how='all')
                    if not df_tot_mes.empty:
                        fila = dibujar_mapa(df_tot_mes, f"{z.capitalize()} visitas totales resumen mensual", fila, 'int', ["#FFFFFF", "#C6E0B4", "#548235"], 'line')
                    
                    for mes in df_z['Mes_Año'].cat.categories:
                        df_mes = df_z[df_z['Mes_Año'] == mes]
                        if not df_mes.empty:
                            df_tot_sem = df_mes.pivot_table(index='Semana_Mes', columns='Día semana', values='total_visits', aggfunc='sum', observed=True).dropna(how='all')
                            if not df_tot_sem.empty:
                                fila = dibujar_mapa(df_tot_sem, f"{z.capitalize()} visitas totales desglose semanal {mes}", fila, 'int', ["#FFFFFF", "#C6E0B4", "#548235"], 'line')
                else:
                    df_tot_sem = df_z.pivot_table(index='Semana_Mes', columns='Día semana', values='total_visits', aggfunc='sum', observed=True).dropna(how='all')
                    if not df_tot_sem.empty:
                        fila = dibujar_mapa(df_tot_sem, f"{z.capitalize()} visitas totales desglose semanal", fila, 'int', ["#FFFFFF", "#C6E0B4", "#548235"], 'line')
                
            if 'new_visitors' in df_z.columns:
                if mostrar_mensual:
                    df_new_mes = df_z.pivot_table(index='Mes_Año', columns='Día semana', values='new_visitors', aggfunc='sum', observed=True).dropna(how='all')
                    if not df_new_mes.empty:
                        fila = dibujar_mapa(df_new_mes, f"{z.capitalize()} nuevos visitantes resumen mensual", fila, 'int', ["#FFFFFF", "#E4DFEC", "#7030A0"], 'line')
                    
                    for mes in df_z['Mes_Año'].cat.categories:
                        df_mes = df_z[df_z['Mes_Año'] == mes]
                        if not df_mes.empty:
                            df_new_sem = df_mes.pivot_table(index='Semana_Mes', columns='Día semana', values='new_visitors', aggfunc='sum', observed=True).dropna(how='all')
                            if not df_new_sem.empty:
                                fila = dibujar_mapa(df_new_sem, f"{z.capitalize()} nuevos visitantes desglose semanal {mes}", fila, 'int', ["#FFFFFF", "#E4DFEC", "#7030A0"], 'line')
                else:
                    df_new_sem = df_z.pivot_table(index='Semana_Mes', columns='Día semana', values='new_visitors', aggfunc='sum', observed=True).dropna(how='all')
                    if not df_new_sem.empty:
                        fila = dibujar_mapa(df_new_sem, f"{z.capitalize()} nuevos visitantes desglose semanal", fila, 'int', ["#FFFFFF", "#E4DFEC", "#7030A0"], 'line')
                
        ws.write(fila, 0, "Tiempo medio de estancia en minutos", fmt_title)
        fila += 2
        for z in zonas_ordenadas:
            df_z = df_loc[df_loc['Zona'] == z]
            if 'dwell_time' in df_z.columns:
                if mostrar_mensual:
                    df_d_mes = df_z.pivot_table(index='Mes_Año', columns='Día semana', values='dwell_time', aggfunc='mean', observed=True).dropna(how='all')
                    if not df_d_mes.empty:
                        fila = dibujar_mapa(df_d_mes, f"{z.capitalize()} tiempo de estancia resumen mensual", fila, 'float', ["#FFFFFF", "#9BC2E6", "#2F75B5"], 'line')
                    
                    for mes in df_z['Mes_Año'].cat.categories:
                        df_mes = df_z[df_z['Mes_Año'] == mes]
                        if not df_mes.empty:
                            df_d_sem = df_mes.pivot_table(index='Semana_Mes', columns='Día semana', values='dwell_time', aggfunc='mean', observed=True).dropna(how='all')
                            if not df_d_sem.empty:
                                fila = dibujar_mapa(df_d_sem, f"{z.capitalize()} tiempo de estancia desglose semanal {mes}", fila, 'float', ["#FFFFFF", "#9BC2E6", "#2F75B5"], 'line')
                else:
                    df_d_sem = df_z.pivot_table(index='Semana_Mes', columns='Día semana', values='dwell_time', aggfunc='mean', observed=True).dropna(how='all')
                    if not df_d_sem.empty:
                        fila = dibujar_mapa(df_d_sem, f"{z.capitalize()} tiempo de estancia desglose semanal", fila, 'float', ["#FFFFFF", "#9BC2E6", "#2F75B5"], 'line')

        col_dist = 'dwell_hist' if 'dwell_hist' in df_loc.columns else ('dwell_distribution' if 'dwell_distribution' in df_loc.columns else ('dwell_dict' if 'dwell_dict' in df_loc.columns else None))
        if col_dist:
            ws.write(fila, 0, "Distribucion de tiempo de estancia fidelidad de clientes", fmt_title)
            fila += 1
            dist_data = []
            for z in zonas_ordenadas:
                df_z = df_loc[df_loc['Zona'] == z]
                sum_dict = {}
                for d in df_z[col_dist].dropna():
                    parsed = safely_eval_dwell_dict(d)
                    if isinstance(parsed, dict):
                        for k, v in parsed.items():
                            sum_dict[k] = sum_dict.get(k, 0) + int(v)
                    elif isinstance(parsed, list):
                        mapa_nombres = {
                            'd_000_002': 'Rebote 0-2 min', 'd_002_005': '2 a 5 min', 
                            'd_005_010': '5 a 10 min', 'd_010_030': '10 a 30 min', 
                            'd_010_060': '10 a 60 min', 'd_030_060': '30 a 60 min', 
                            'd_060_120': '1 a 2 horas', 'd_120_240': 'Mas de 2h'
                        }
                        for item in parsed:
                            if isinstance(item, dict) and 'minutes' in item:
                                k = mapa_nombres.get(item['minutes'], item['minutes'])
                                sum_dict[k] = sum_dict.get(k, 0) + int(item.get('value', 0))
                                
                sum_dict['Zona'] = z
                dist_data.append(sum_dict)
                
            if dist_data:
                df_dist = pd.DataFrame(dist_data).fillna(0).set_index('Zona')
                pos_cols = ['Rebote 0-2 min', '2 a 5 min', '5 a 10 min', '10 a 30 min', '10 a 60 min', '30 a 60 min', '1 a 2 horas', 'Mas de 2h']
                cols_present = [c for c in pos_cols if c in df_dist.columns]
                oth_cols = [c for c in df_dist.columns if c not in pos_cols]
                df_dist = df_dist[cols_present + oth_cols]
                
                ws.write(fila, 0, "Zona", fmt_header)
                for c_idx, c in enumerate(df_dist.columns):
                    ws.write(fila, c_idx + 1, c, fmt_header)
                fila += 1
                
                for r_idx, (z, row_data) in enumerate(df_dist.iterrows()):
                    ws.write(fila, 0, z, fmt_header)
                    for c_idx, val in enumerate(row_data):
                        ws.write(fila, c_idx + 1, val, fmt_int)
                    fila += 1
                fila += 3

        ws.write(fila, 0, "Visitas totales medias por hora", fmt_title)
        fila += 1
        
        horas_exp = pd.DataFrame(df_loc['hourly_visits'].apply(safely_eval_hours).to_list(), index=df_loc.index)
        horas_exp.columns = [f"{i:02d}:00" for i in range(24)]
        df_calor = pd.concat([df_loc[['Zona']], horas_exp], axis=1)
        df_hora = df_calor.groupby('Zona').mean().T.round(0).fillna(0)
        df_hora = df_hora.reindex(columns=[z for z in zonas_ordenadas if z in df_hora.columns])
        
        ws.write(fila, 0, "Hora", fmt_header)
        for c_idx, z in enumerate(df_hora.columns):
            ws.write(fila, c_idx + 1, z, fmt_header)
        fila += 1
        
        fila_inicio_hora = fila
        for r_idx, (hora, row_data) in enumerate(df_hora.iterrows()):
            ws.write(fila, 0, hora, fmt_header)
            for c_idx, val in enumerate(row_data):
                ws.write(fila, c_idx + 1, val, fmt_int)
            fila += 1
            
        ws.conditional_format(fila_inicio_hora, 1, fila - 1, len(df_hora.columns), {
            'type': '3_color_scale', 'min_color': "#FFFFFF", 'mid_color': "#FFE082", 'max_color': "#F44336"
        })
            
        col_calle_hora = [i for i, z in enumerate(df_hora.columns) if 'calle' in str(z).lower() or 'exterior' in str(z).lower()]
        col_int_hora = [i for i, z in enumerate(df_hora.columns) if 'calle' not in str(z).lower() and 'exterior' not in str(z).lower()]
        
        offset_chart_row = fila_inicio_hora - 1
        if col_int_hora:
            chart_hora_int = workbook.add_chart({'type': 'line'})
            for i in col_int_hora:
                chart_hora_int.add_series({
                    'name': [sheet_name, fila_inicio_hora - 1, i + 1],
                    'categories': [sheet_name, fila_inicio_hora, 0, fila_inicio_hora + 23, 0],
                    'values': [sheet_name, fila_inicio_hora, i + 1, fila_inicio_hora + 23, i + 1],
                })
            chart_hora_int.set_title({'name': 'Visitas totales medias por hora interior', 'name_font': {'size': 14}})
            chart_hora_int.set_size({'width': 1200, 'height': 350})
            ws.insert_chart(offset_chart_row, len(df_hora.columns) + 2, chart_hora_int)
            offset_chart_row += 20
            
        if col_calle_hora:
            chart_hora_ext = workbook.add_chart({'type': 'line'})
            for i in col_calle_hora:
                chart_hora_ext.add_series({
                    'name': [sheet_name, fila_inicio_hora - 1, i + 1],
                    'categories': [sheet_name, fila_inicio_hora, 0, fila_inicio_hora + 23, 0],
                    'values': [sheet_name, fila_inicio_hora, i + 1, fila_inicio_hora + 23, i + 1],
                })
            chart_hora_ext.set_title({'name': 'Visitas totales medias por hora exterior', 'name_font': {'size': 14}})
            chart_hora_ext.set_size({'width': 1200, 'height': 350})
            ws.insert_chart(offset_chart_row, len(df_hora.columns) + 2, chart_hora_ext)