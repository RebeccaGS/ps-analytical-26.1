import os
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import mapclassify
from shapely import wkt
import streamlit as st
import folium
from streamlit_folium import st_folium

#interface inicial

st.set_page_config(page_title='Painel de Risco no Transporte Coletivo no Rio de Janeiro',
                   layout='wide')
st.title("Painel de Exposição ao Risco no Transporte Coletivo")
st.write("Esse painel tem como objetivo ajudar agentes de segurança pública a visualizar regiões e linhas com maior exposição a roubos. A análise foi feita cruzando dados de roubos em coletivos, áreas de CISP e linhas de ônibus ")

#abrir os arquivos

path_data = os.path.join("../data")
path_shape = os.path.join("../data", "shapes", "lm_cisp_bd.shp")

@st.cache_data #carrega o dataset com as infos de crime
def carregar_crimes(path_data):
    df_delegacia = pd.read_csv(f"{path_data}/delegacia.csv", encoding="iso-8859-1", sep=';')

    colunas_delegacia = ['cisp', 'mes', 'ano', 'roubo_em_coletivo', 'risp']

    crimes_interesse = df_delegacia[colunas_delegacia].copy()

    crimes_interesse["cisp"] = pd.to_numeric(crimes_interesse["cisp"], errors="coerce")
    crimes_interesse["ano"] = pd.to_numeric(crimes_interesse["ano"], errors="coerce")
    crimes_interesse["risp"] = pd.to_numeric(crimes_interesse["risp"], errors="coerce")
    crimes_interesse["mes"] = pd.to_numeric(crimes_interesse["mes"], errors="coerce")
    crimes_interesse['roubo_em_coletivo'] = pd.to_numeric(crimes_interesse['roubo_em_coletivo'], errors="coerce")


    return crimes_interesse

@st.cache_data  #Aqui o usuario vai poder escolher mes e ano(mes 0 equivale a todos, um panorama geral do ano)
def preparar_crimes_por_cisp(crimes_interesse, ano, mes):
    crimes_interesse = crimes_interesse[
        (crimes_interesse["ano"] == ano) &
        (crimes_interesse["risp"] <= 2)
    ].copy()

    if mes!= 0:
        crimes_interesse = crimes_interesse[crimes_interesse["mes"] == mes].copy()

    crimes_por_cisp = crimes_interesse.groupby(
        "cisp",
        as_index=False
    )["roubo_em_coletivo"].sum()

    crimes_por_cisp_ordenado = crimes_por_cisp.sort_values(by="roubo_em_coletivo", ascending=False)

    return crimes_por_cisp_ordenado

@st.cache_data
def carregar_onibus(path_data): #aqui carregamos as infos dos onibus(linhas, numero, etc)
    df_rotas = pd.read_csv(f"{path_data}/routes.csv")
    df_trips = pd.read_parquet(f"{path_data}/trips")

    colunas_rotas = ['route_id', 'route_short_name', 'route_long_name']
    rotas_interesse = df_rotas[colunas_rotas]

    colunas_trips = ['route_id', 'trip_headsign', 'trip_short_name', 'direction_id', 'shape_id']
    trips_interesse = df_trips[colunas_trips]

    infos_dos_bus_com_duplicatas = rotas_interesse.merge(trips_interesse, on='route_id')
    infos_dos_bus = infos_dos_bus_com_duplicatas.drop_duplicates(subset=['route_id', 'direction_id']).copy()

    infos_dos_bus['ida'] = (infos_dos_bus['direction_id'] == 0).astype(int)
    infos_dos_bus['volta'] = (infos_dos_bus['direction_id'] == 1).astype(int)
    infos_dos_bus.drop(columns='direction_id', inplace=True)

    dicio_infos_dos_bus = {
        'route_short_name': 'numero',
        'route_long_name': 'descricao',
        'trip_headsign': 'nome'
    }
    infos_dos_bus.rename(columns=dicio_infos_dos_bus, inplace=True)
    infos_dos_bus['numero'] = infos_dos_bus['numero'].astype(str)

    return infos_dos_bus

@st.cache_data #aqui carregamos mapa com cisps
def carregar_mapa(path_shape, crimes_por_cisp_ordenado):
    mapa_cisp = gpd.read_file(path_shape)
    mapa_cisp['cisp'] = pd.to_numeric(mapa_cisp['cisp'], errors='coerce')

    mapa_cisp_final = mapa_cisp.merge(crimes_por_cisp_ordenado, on='cisp')

    mapa_cisp_final['roubo_em_coletivo'] = mapa_cisp_final['roubo_em_coletivo'].fillna(0) #cisp sumindo sem roubo no mes

    return mapa_cisp_final

@st.cache_data #desenha as linhas de onibus com geopandas
def carregar_linhas(path_data, infos_dos_bus):
    shapes = pd.read_parquet(f"{path_data}/shapes_geom")

    shapes_filtrados = shapes[shapes['shape_id'].isin(infos_dos_bus['shape_id'])]
    bus_com_trajeto = shapes_filtrados.merge(infos_dos_bus, on='shape_id')

    # converte o texto de linestring() em linha matematica p gpd entender que da pra desenhar linha de rota
    bus_com_trajeto['geometry'] = bus_com_trajeto['shape'].apply(wkt.loads)

    colunas_inuteis = ['feed_version', 'feed_start_date', 'feed_end_date', 'shape_distance', 'start_pt', 'end_pt',
                       'versao_modelo', 'shape']
    bus_com_trajeto.drop(columns=colunas_inuteis, inplace=True, errors='ignore')

    linhas_onibus_geo = gpd.GeoDataFrame(bus_com_trajeto, geometry='geometry', crs="EPSG:4326")

    return linhas_onibus_geo

#nao permitiu cache...
def cruzar_linhas_cisp(linhas_onibus_geo, mapa_cisp_final):
        mapa_final_duplicado = gpd.sjoin(
            linhas_onibus_geo,
            mapa_cisp_final,
            predicate="intersects"
        )

        mapa_final = mapa_final_duplicado.drop_duplicates(
            subset=["route_id", "ida", "volta", "cisp"]
        )

        return mapa_final

#nao permitiu cache...
def risco(mapa_final):
    risco_por_linha = mapa_final.groupby(['route_id', 'ida', 'volta', 'numero'], as_index=False)['roubo_em_coletivo'].sum()

    risco_por_linha.rename(columns={'roubo_em_coletivo': 'exposicao_roubo_total'}, inplace=True)

    risco_por_linha = risco_por_linha.sort_values(by = 'exposicao_roubo_total', ascending=False)

    risco_por_linha['nota_risco'], limites = pd.cut(risco_por_linha['exposicao_roubo_total'],bins=5,labels=[1, 2, 3, 4, 5],retbins=True)

    risco_por_linha['nota_risco'] = risco_por_linha['nota_risco'].astype('Int64')

    return risco_por_linha

#Opçoes do usuario - lista de opcoes + opcao de nao marcar mes para exibir o ano todo
ano_escolhido = st.sidebar.selectbox(
    "Ano",
    [2022, 2023, 2024, 2025, 2026]
)

meses = {
    "Todos": 0,
    "Janeiro": 1,
    "Fevereiro": 2,
    "Março": 3,
    "Abril": 4,
    "Maio": 5,
    "Junho": 6,
    "Julho": 7,
    "Agosto": 8,
    "Setembro": 9,
    "Outubro": 10,
    "Novembro": 11,
    "Dezembro": 12
}

mes_nome = st.sidebar.selectbox("Mês", list(meses.keys()))
mes_escolhido = meses[mes_nome]

#Abrindo arquivos...

crimes_interesse = carregar_crimes(path_data)

crimes_por_cisp_ordenado = preparar_crimes_por_cisp(crimes_interesse, ano_escolhido, mes_escolhido)

infos_dos_bus = carregar_onibus(path_data)

mapa_cisp_final = carregar_mapa(path_shape, crimes_por_cisp_ordenado)

linhas_onibus_geo = carregar_linhas(path_data, infos_dos_bus)

mapa_com_linhas = cruzar_linhas_cisp(linhas_onibus_geo, mapa_cisp_final)

risco_por_linha = risco(mapa_com_linhas)

aba_mapa, aba_geral, aba_linha, aba_ranking, aba_metodologia = st.tabs(
    [
        "Mapa",
        "Geral",
        "Análise por Linha",
        "Ranking",
        "Metodologia"
    ]
)


with aba_mapa:
    st.header("Mapa de calor sobre roubos em coletivos por CISP")
    if(mes_escolhido == 0):
        st.write(f"Mapa das áreas de CISP em {ano_escolhido}")
    else:
        st.write(f"Mapa das áreas de CISP em {mes_escolhido}/{ano_escolhido}")

    mapa_cisp_folium = mapa_cisp_final.to_crs(epsg=4326)

    centro = mapa_cisp_folium.geometry.unary_union.centroid

    mapa = folium.Map(
        location=[centro.y, centro.x],
        zoom_start=11,
        tiles="CartoDB positron"
    )

    folium.Choropleth(
        geo_data=mapa_cisp_folium,
        data=mapa_cisp_folium,
        columns=["cisp", "roubo_em_coletivo"],
        key_on="feature.properties.cisp",
        fill_color="Reds",
        fill_opacity=0.7,
        line_opacity=0.4,
        legend_name="Roubos em coletivo"
    ).add_to(mapa)

    folium.GeoJson(
        mapa_cisp_folium,
        name="Informações da CISP",
        style_function=lambda feature: {
            "fillColor": "transparent",
            "color": "black",
            "weight": 0.7,
            "fillOpacity": 0,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["cisp", "roubo_em_coletivo"],
            aliases=["CISP:", "Roubos em coletivo:"],
            localize=True,
            sticky=True,
            labels=True
        )
    ).add_to(mapa)

    st_folium(
        mapa,
        width=900,
        height=600
    )
#with aba_geral:



#with aba_linha:
    st.header("Análise por Linha de Ônibus")



#with aba_ranking:
    st.header("Ranking de Linhas")



#with aba_metodologia:
    st.header("Metodologia")























