# Otimização de Alocação de Espectro 5G
Fase 1 - Projeto

Dashboard Streamlit em que **um único conjunto de torres** (P1…P10, com posição e potência) alimenta todos os
gráficos. Mudar a quantidade de pontos, a área ou editar uma torre na tabela recalcula tudo; cada gráfico tem
seus **controles logo abaixo, na horizontal**, e uma **legenda** explicando o que o gráfico mostra e o que cada
variável faz.

1. **Torres (pontos)** — cenário compartilhado: quantidade (0–10), área, sementes, potência; tabela editável.
2. **Voronoi clássico** — células, fronteiras (mediatrizes) e distâncias (média/mediana geral e entre vizinhos).
3. **Power-Voronoi 5G** — peso pela potência Tx; faixa, ganho de antena, expoente de perda, RSRP mínimo.
4. **Sinal real** — melhor servidor ponto a ponto, curvas de RSRP e comparação com o Power-Voronoi.
5. **Rede e canais** — usuários (hotspot), grafo de interferência e alocação de canais entre vizinhos.
6. **SINR** — distribuição do SINR, outage, throughput (Shannon) e equidade de Jain.

O **ⓘ** em cada ponto reúne dados de todos os gráficos (posição, potência, raio, vizinhos, áreas, canal, carga).

## Rodar

No Windows, dê **duplo clique em `rodar.bat`**: na primeira vez ele cria o ambiente `.venv` e instala as
dependências; depois abre o painel no navegador (http://localhost:8501). Mantenha a janela preta aberta enquanto
usa o painel — se ela for fechada, a página para de recalcular.

Ou manualmente:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Testes

```bash
pip install pytest
python -m pytest -q
```

## Arquivos

- `app.py` — layout: seções, controles abaixo de cada gráfico, legendas e métricas
- `explorer_ui.py` — cálculo compartilhado (`compute`) e gráficos Plotly
- `explorer_geometry.py` — núcleo numérico (células por recorte de semiplanos, distâncias, propagação), sem Streamlit
- `radio.py` — usuários, alocação de canais e SINR, sem Streamlit
- `tests/` — testes do núcleo geométrico e do rádio
