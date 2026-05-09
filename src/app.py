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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

path_data = os.path.join(BASE_DIR, "data")
path_shape = os.path.join(BASE_DIR, "data", "shapes", "lm_cisp_bd.shp") #correçao do caminho, base dir vai pra ps-analytical

@st.cache_data #carrega o dataset com as infos de crime
def carregar_crimes(path_data):
    colunas_delegacia = ['cisp', 'mes', 'ano', 'roubo_em_coletivo', 'risp']
    df_delegacia = pd.read_csv(f"{path_data}/delegacia.csv", encoding="iso-8859-1", sep=';', usecols=colunas_delegacia)

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
    colunas_rotas = ['route_id', 'route_short_name', 'route_long_name']
    rotas_interesse = pd.read_csv(f"{path_data}/routes.csv", usecols=colunas_rotas )
    colunas_trips = ['route_id', 'trip_headsign', 'trip_short_name', 'direction_id', 'shape_id']
    trips_interesse = pd.read_parquet(f"{path_data}/trips", columns=colunas_trips)


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

@st.cache_data
def criar_base_espacial(_linhas_onibus_geo, path_shape):
    mapa_cisp_puro = gpd.read_file(path_shape)
    mapa_cisp_puro['cisp'] = pd.to_numeric(mapa_cisp_puro['cisp'], errors='coerce')

    intersecao = gpd.sjoin(linhas_onibus_geo, mapa_cisp_puro, predicate="intersects")

    intersecao = intersecao.drop_duplicates(subset=['route_id', 'ida','volta','cisp'])

    return intersecao[['route_id', 'ida', 'volta', 'numero', 'cisp']]

@st.cache_data
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


meses_completos = {
    "Todos": 0, "Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4,
    "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8, "Setembro": 9,
    "Outubro": 10, "Novembro": 11, "Dezembro": 12
}


if ano_escolhido == 2026:
    opcoes_meses = ["Todos", "Janeiro", "Fevereiro", "Março"]
else:
    opcoes_meses = list(meses_completos.keys())


mes_nome = st.sidebar.selectbox("Mês", opcoes_meses)
mes_escolhido = meses_completos[mes_nome]

esconder_linhas = st.checkbox("Esconder linhas de onibus")

#Abrindo arquivos...

crimes_interesse = carregar_crimes(path_data)

crimes_por_cisp_ordenado = preparar_crimes_por_cisp(crimes_interesse, ano_escolhido, mes_escolhido)

infos_dos_bus = carregar_onibus(path_data)

stops = carregar_stop(path_data)

mapa_cisp_final = carregar_mapa(path_shape, crimes_por_cisp_ordenado)

linhas_onibus_geo = carregar_linhas(path_data, infos_dos_bus)

base = criar_base_espacial(linhas_onibus_geo, path_shape)

mapa_com_linhas = base.merge(crimes_por_cisp_ordenado, on='cisp', how='left')
mapa_com_linhas['roubo_em_coletivo'] = mapa_com_linhas['roubo_em_coletivo'].fillna(0)

risco_por_linha = risco(mapa_com_linhas)

col_mapa, col_info, col_vazia = st.columns([6, 3, 1], gap="small")

linhas_disponiveis = sorted(linhas_onibus_geo["numero"].dropna().unique())

linha_escolhida = st.sidebar.selectbox(
    "Escolha uma linha de ônibus",
    ["Selecione uma linha"] + linhas_disponiveis
)

linha_foi_escolhida = linha_escolhida != "Selecione uma linha"

if linha_foi_escolhida:
    sentido_escolhido = st.sidebar.selectbox(
        "Escolha o sentido",
        ["Ambos os sentidos", "Ida", "Volta"]
    )

    linha_a_exibir = linhas_onibus_geo[
        linhas_onibus_geo["numero"] == linha_escolhida
    ].copy()

    ida = linha_a_exibir[linha_a_exibir["ida"] == 1].copy()
    volta = linha_a_exibir[linha_a_exibir["volta"] == 1].copy()

#Ponto de chegada
#ponto de partida
#Escolha uma linha de onibus

with col_mapa:
    st.header("Mapa de calor sobre roubos em coletivos por CISP")
    if mes_escolhido == 0:
        st.write(f"Mapa das áreas de CISP em {ano_escolhido}")
    else:
        st.write(f"Mapa das áreas de CISP em {mes_escolhido}/{ano_escolhido}")

    mapa_cisp_folium = mapa_cisp_final.to_crs(epsg=4326)

    centro = mapa_cisp_folium.geometry.union_all().centroid

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

    folium.GeoJson( #Camada invisivel
        mapa_cisp_folium,
        name="Informações da CISP",
        style_function=lambda feature: {    #pega o limite das regioes para mostrar a box
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

    if not esconder_linhas:
        folium.GeoJson(
            linhas_onibus_geo,
            name=f"Linha {linhas_disponiveis} - Ida",
            style_function=lambda feature: {
                "color": "black",
                "weight": 1,
                "opacity": 0.3,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["numero", "nome"],
                aliases=["Linha:", "Destino:"],
                sticky=True,
                labels=True
            )
        ).add_to(mapa)


    if linha_foi_escolhida:
        if sentido_escolhido in ['Ambos os sentidos', 'Ida'] and not ida.empty:
            folium.GeoJson(
                ida,
                name=f"Linha {linha_escolhida} - Ida",
                style_function=lambda feature: {
                    "color": "blue",
                    "weight": 4,
                    "opacity": 0.8,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["numero", "nome"],
                    aliases=["Linha:", "Destino:"],
                    sticky=True,
                    labels=True
                )
            ).add_to(mapa)
        if sentido_escolhido in ['Ambos os sentidos', 'Volta'] and not volta.empty:
            folium.GeoJson(
                volta,
                name=f"Linha {linha_escolhida} - Volta",
                style_function=lambda feature: {
                    "color": "green",
                    "weight": 4,
                    "opacity": 0.8,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["numero", "nome"],
                    aliases=["Linha:", "Destino:"],
                    sticky=True,
                    labels=True
                )
            ).add_to(mapa)

    st_folium(
        mapa,
        width=1100,
        height=800
    )

with col_info:
    st.subheader("Análise do risco associado à linha no período escolhido")
    if linha_foi_escolhida:
        dados_linha = risco_por_linha[risco_por_linha['numero'] == linha_escolhida]
        print(dados_linha)
        if not dados_linha.empty:
            nota = dados_linha['nota_risco'].values[0]
            total_roubos = dados_linha['exposicao_roubo_total'].values[0]

            st.write(f"Linha selecionada: {linha_escolhida}")
            st.metric(label="Nível de Risco(1 a 5)", value = int(nota))
            st.metric(label="Exposição total de roubos nas CISPs da Rota: ", value=int(total_roubos))

            st.write("A nota de risco foi calculada fazendo o somatório de roubos a coletivos registrados nas CISPs por onde a linha de ônibus passa durante todo o seu trajeto.")

        else:
            st.warning("Não há dados para essa rota!")

    else:
        st.write("Selecione uma linha de onibus no menu para obter o risco associado")
