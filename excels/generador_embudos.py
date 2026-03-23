import pandas as pd
import numpy as np

def generar_excel_embudos(df_filt, writer, workbook):
    fmt_h = workbook.add_format({'bold': True, 'bg_color': '#203764', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_h_pct = workbook.add_format({'bold': True, 'bg_color': '#C65911', 'font_color': 'white', 'border': 1, 'align': 'center'})
    fmt_h_uni = workbook.add_format({'bold': True, 'bg_color': '#375623', 'font_color': 'white', 'border': 1, 'align': 'center'}) # Encabezado verde para Únicos
    fmt_int = workbook.add_format({'num_format': '#,##0', 'align': 'center', 'border': 1})
    fmt_pct = workbook.add_format({'num_format': '0.0%', 'align': 'center', 'border': 1})
    fmt_date = workbook.add_format({'num_format': 'yyyy-mm-dd', 'align': 'center', 'border': 1})

    for loc in df_filt['Ubicación'].unique():
        df_loc = df_filt[df_filt['Ubicación'] == loc]
        sheet_name = str(loc)[:31].replace(':', '').replace('/', '')
        
        # Ordenamos las zonas de esta tienda por volumen para construir el embudo
        orden_zonas = df_loc.groupby('Zona')['total_visits'].sum().sort_values(ascending=False).index.tolist()
        
        # Pivotamos los datos de volumen total por zonas
        df_pivot = df_loc.pivot_table(index='fecha', columns='Zona', values='total_visits', aggfunc='sum', observed=True).reset_index().fillna(0)
        
        # ====================================================================
        # NUEVO: EXTRACCIÓN DE VISITANTES ÚNICOS DEDUPLICADOS
        # ====================================================================
        if len(orden_zonas) > 0:
            zona_principal = orden_zonas[0] # La zona con más tráfico (entrada/local)
            # Extraemos los únicos solo de esa zona principal por cada día
            df_unicos = df_loc[df_loc['Zona'] == zona_principal].groupby('fecha')['unique_visitors'].sum().reset_index()
            df_unicos.rename(columns={'unique_visitors': 'Únicos (Local)'}, inplace=True)
            # Lo fusionamos con nuestro embudo
            df_pivot = pd.merge(df_pivot, df_unicos, on='fecha', how='left').fillna(0)
        else:
            df_pivot['Únicos (Local)'] = 0
            
        # ====================================================================
        
        # Construimos el orden de las columnas final
        cols_finales = ['fecha', 'Únicos (Local)'] # Insertamos Únicos al principio del embudo
        
        for i in range(len(orden_zonas)):
            z_act = orden_zonas[i]
            cols_finales.append(z_act)
            
            # Si hay una zona siguiente más pequeña, calculamos el drop-off
            if i < len(orden_zonas) - 1:
                z_sig = orden_zonas[i+1]
                nombre_pct = f"%({z_act[:3]}>{z_sig[:3]})"
                df_pivot[nombre_pct] = (df_pivot[z_sig] / df_pivot[z_act]).replace([np.inf, -np.inf], 0).fillna(0)
                cols_finales.append(nombre_pct)

        df_pivot = df_pivot[cols_finales].sort_values('fecha')
        
        df_pivot.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        
        ws.set_column('A:A', 14, fmt_date)
        col_idx = 1
        for col in cols_finales[1:]:
            if '%' in col:
                ws.set_column(col_idx, col_idx, 12, fmt_pct)
                # Escala absoluta del 0% al 100% para los porcentajes
                ws.conditional_format(1, col_idx, len(df_pivot), col_idx, {
                    'type': '2_color_scale',
                    'min_color': "#F8696B", 'min_type': 'num', 'min_value': 0,
                    'max_color': "#63BE7B", 'max_type': 'num', 'max_value': 1
                })
            elif col == 'Únicos (Local)':
                ws.set_column(col_idx, col_idx, 16, fmt_int)
                # Escala de calor verde para los únicos (igual que en operativo)
                ws.conditional_format(1, col_idx, len(df_pivot), col_idx, {
                    'type': '3_color_scale', 
                    'min_color': "#FFFFFF", 
                    'mid_color': "#C6E0B4", 
                    'max_color': "#548235"
                })
            else:
                ws.set_column(col_idx, col_idx, 14, fmt_int)
            col_idx += 1

        for c_idx, col_name in enumerate(cols_finales):
            if '%' in col_name: 
                ws.write(0, c_idx, col_name, fmt_h_pct)
            elif col_name == 'Únicos (Local)': 
                ws.write(0, c_idx, col_name, fmt_h_uni)
            else: 
                ws.write(0, c_idx, col_name, fmt_h)