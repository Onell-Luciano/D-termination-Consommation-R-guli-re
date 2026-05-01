import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from io import BytesIO
import math
from sqlalchemy import create_engine, text

# Ouverture du chemin vers la base de donnée
engine = create_engine("postgresql+psycopg2://postgres:geldy@localhost:5432/stock_db")

# --- CONFIGURATION ---
st.set_page_config(page_title="Gestion de Stock", page_icon="📉", layout="wide", initial_sidebar_state="expanded")

# Thème sombre CSS personnalisé (Streamlit est déjà sombre, on ajoute juste quelques finitions)
st.markdown("""
    <style>
    .stMetric {
        background-color: #1e1e1e;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.4);
        border: 1px solid #333;
    }
    div[data-testid="stMetricValue"] {
        color: #00b4d8;
    }
    .stDataFrame {
        border-radius: 5px;
    }
    /* === Bouton Mettre à jour : lueur bleue au survol === */
    .update-btn button {
        background-color: transparent;
        color: #00b4d8;
        border: 2px solid #00b4d8;
        border-radius: 8px;
        font-weight: 600;
        letter-spacing: 0.5px;
        transition: all 0.25s ease;
        box-shadow: 0 0 0px rgba(0, 180, 216, 0);
    }
    .update-btn button:hover {
        background-color: rgba(0, 180, 216, 0.1);
        border-color: #00d4f5;
        color: #00d4f5;
        box-shadow: 0 0 14px rgba(0, 180, 216, 0.7), 0 0 30px rgba(0, 180, 216, 0.3);
        transform: translateY(-1px);
    }
    .update-btn button:active {
        transform: translateY(0px);
        box-shadow: 0 0 8px rgba(0, 180, 216, 0.5);
    }
    </style>
""", unsafe_allow_html=True)

# --- FONCTIONS MÉTIER ---

def save_simulation(params, results, df_main, df_synth):
    """Fonction pour sauvegarder les données de simulation dans la base de donnée PostgreSQL"""
    query = text("""
        INSERT INTO simulation_stock (
            conso_annuelle, conso_mensuelle, prix_unitaire,
            cout_passation, taux_possession, delai_appro, stock_secu_mois,
            N, Q, periode, point_commande,
            df_main, df_synth
        ) VALUES (
            :conso_annuelle, :conso_mensuelle, :prix_unitaire,
            :cout_passation, :taux_possession, :delai_appro, :stock_secu_mois,
            :N, :Q, :periode, :point_commande,
            :df_main, :df_synth
        )
    """)

    with engine.connect() as conn:
        conn.execute(query, {
            **params,
            **results,
            "df_main": df_main.to_json(orient="records"),
            "df_synth": df_synth.to_json(orient="split")
        })
        conn.commit()

def load_simulations():
    """Fonction pour charger les données de simulation depuis la base de donnée PostgreSQL"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM simulation_stock ORDER BY id DESC"))
        return result.fetchall()

def delete_simulation(sim_id):
    """Fonction pour supprimer une sauvegarde de la base de données"""
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM simulation_stock WHERE id = :id"), {"id": sim_id})
        conn.commit()

def update_simulation(sim_id, params, results, df_main, df_synth):
    """Fonction pour mettre à jour une simulation existante dans la base de données"""
    query = text("""
        UPDATE simulation_stock SET
            conso_annuelle=:conso_annuelle, conso_mensuelle=:conso_mensuelle, prix_unitaire=:prix_unitaire,
            cout_passation=:cout_passation, taux_possession=:taux_possession, delai_appro=:delai_appro,
            stock_secu_mois=:stock_secu_mois, N=:N, Q=:Q, periode=:periode, point_commande=:point_commande,
            df_main=:df_main, df_synth=:df_synth
        WHERE id = :id
    """)
    with engine.connect() as conn:
        conn.execute(query, {
            **params, **results,
            "df_main": df_main.to_json(orient="records"),
            "df_synth": df_synth.to_json(orient="split"),
            "id": sim_id
        })
        conn.commit()

import json
from io import StringIO

def json_to_df(df_main_json, df_synth_json):
    """Convertir les données JSON en DataFrames"""
    # Si les données proviennent de PostgreSQL JSONB (dict/list), on les reconvertit en string
    if not isinstance(df_main_json, str):
        df_main_json = json.dumps(df_main_json)
    df_main = pd.read_json(StringIO(df_main_json), orient="records")
        
    if not isinstance(df_synth_json, str):
        df_synth_json = json.dumps(df_synth_json)
        
    try:
        # Nouveau format de sauvegarde
        df_synth = pd.read_json(StringIO(df_synth_json), orient="split")
    except ValueError:
        # Rétrocompatibilité avec les anciennes simulations sauvegardées
        df_synth = pd.read_json(StringIO(df_synth_json))
    
    return df_main, df_synth

def calcul_stock(conso_annuelle, conso_mensuelle, prix_unitaire, cout_passation, taux_possession, delai_appro, stock_secu_mois):
    """Calcule les indicateurs clés du modèle de Wilson avec protections contre les erreurs."""
    try:
        # Sécurisation des entrées
        conso_annuelle = max(0.0, float(conso_annuelle or 0))
        conso_mensuelle = max(0.0, float(conso_mensuelle or 0))
        prix_unitaire = max(0.0, float(prix_unitaire or 0))
        cout_passation = max(0.0, float(cout_passation or 0))
        taux_possession = max(0.0, float(taux_possession or 0))
        delai_appro = max(0.0, float(delai_appro or 0))
        stock_secu_mois = max(0.0, float(stock_secu_mois or 0))

        cout_possession = prix_unitaire * taux_possession
        
        if cout_possession <= 0:
            Q = 0
        else:
            Q = math.sqrt((2 * conso_annuelle * cout_passation) / cout_possession)
            
        if Q > 0:
            N = conso_annuelle / Q
            periode_commandes = 12 / N if N > 0 else 0
        else:
            N = 0
            periode_commandes = 0
            
        stock_secu_qte = stock_secu_mois * conso_mensuelle
        point_commande = stock_secu_qte + (delai_appro * conso_mensuelle)
        
        return round(N, 2), round(Q), round(periode_commandes, 2), round(point_commande)
    except Exception:
        return 0, 0, 0, 0



def generate_table_dynamique(Q, point_commande, delai_appro, stock_initial, df_conso):
    """Génère le tableau principal dynamique basé sur les paramètres et la consommation éditée."""
    df_dyn_main = []
    df_dyn_synth = {"Commande": [], "Livraison": [], "Consommation": [], "Stock": [], "Mois": []}
    
    stock_courant = stock_initial
    commandes_en_attente = [] # Liste de dicts: {"qte": ..., "mois_livraison": ...}
    
    for i, row in df_conso.iterrows():
        m = row["Période"]
        
        # 1. Consommation
        conso_du_mois = row["Consommation"]
        if pd.isna(conso_du_mois):
            conso_du_mois = 0
            
        # 2. Livraison
        livraison_recue = 0
        commandes_restantes = []
        for cmd in commandes_en_attente:
            if i >= cmd["mois_livraison"]:
                livraison_recue += cmd["qte"]
            else:
                commandes_restantes.append(cmd)
        commandes_en_attente = commandes_restantes
        
        # 3. Mise à jour stock
        stock_avec_rupture = stock_courant - conso_du_mois
        stock_rectifie = stock_avec_rupture + livraison_recue
        stock_courant = stock_rectifie
        
        # 4. Calcul stock virtuel
        stock_virtuel = stock_courant + sum(c["qte"] for c in commandes_en_attente)
        
        # 5. Décision de commande
        commande_qte = 0
        commande_date = "-"
        
        if stock_virtuel <= point_commande and not commandes_en_attente and i != len(df_conso) - 1:
            commande_qte = Q
            commande_date = f"Début {m[:3]}"
            mois_livraison = i + math.ceil(delai_appro) if delai_appro > 0 else i + 1
            commandes_en_attente.append({"qte": Q, "mois_livraison": mois_livraison})
        
        # 6. Formatage (0 explicite, plus de "-")
        def fmt(val): return str(int(val))
            
        df_dyn_main.append([
            m, 
            fmt(conso_du_mois), 
            fmt(stock_avec_rupture),
            fmt(livraison_recue),
            fmt(stock_rectifie),
            commande_date,
            fmt(commande_qte) if commande_qte > 0 else "-"
        ])
        
        df_dyn_synth["Mois"].append(m)
        df_dyn_synth["Commande"].append(fmt(commande_qte) if commande_qte > 0 else "-")
        df_dyn_synth["Livraison"].append(fmt(livraison_recue))
        df_dyn_synth["Consommation"].append(fmt(conso_du_mois))
        df_dyn_synth["Stock"].append(fmt(stock_rectifie))

    cols = [
        "Période", "Consommation", "Stock avec rupture éventuelle", 
        "Livraison", "Stock rectifié en fonction des entrées", 
        "Commande (Date)", "Commande (Quantité)"
    ]
    df_main = pd.DataFrame(df_dyn_main, columns=cols)
    
    cols_synth = []
    vus = {}
    for mois in df_dyn_synth["Mois"]:
        if mois in vus:
            vus[mois] += 1
            cols_synth.append(mois + " " * vus[mois])
        else:
            vus[mois] = 0
            cols_synth.append(mois)
            
    df_synth = pd.DataFrame([df_dyn_synth["Commande"], df_dyn_synth["Livraison"], df_dyn_synth["Consommation"], df_dyn_synth["Stock"]], columns=cols_synth)
    df_synth.index = ["Commande", "Livraison", "Consommation", "Stock"]
    
    return df_main, df_synth

def generate_graph(df_synthese, stock_secu_qte):
    """Génère le graphique interactif avec Plotly."""
    stocks_bruts = df_synthese.loc["Stock"].replace("-", "0").astype(float)
    livraisons_brutes = df_synthese.loc["Livraison"].replace("-", "0").astype(float)
    
    livraisons_y = [stocks_bruts.iloc[i] if livraisons_brutes.iloc[i] > 0 else None for i in range(len(stocks_bruts))]
    
    fig = go.Figure()
    
    # Courbe d'évolution du stock
    fig.add_trace(go.Scatter(
        x=df_synthese.columns, 
        y=stocks_bruts,
        mode='lines+markers',
        name='Stock',
        line=dict(color='#00b4d8', width=3, shape='linear'),
        marker=dict(size=8, color='#00b4d8')
    ))
    
    # Points de livraison (Marqueurs verts)
    fig.add_trace(go.Scatter(
        x=df_synthese.columns,
        y=livraisons_y,
        mode='markers',
        name='Livraison reçue',
        marker=dict(color='#00ff00', size=14, symbol='triangle-up', line=dict(color='white', width=1)),
        hovertemplate='Livraison: %{y}<extra></extra>'
    ))
    
    # Ligne du Seuil de sécurité
    fig.add_trace(go.Scatter(
        x=[df_synthese.columns[0], df_synthese.columns[-1]],
        y=[stock_secu_qte, stock_secu_qte],
        mode='lines',
        name='Seuil de Sécurité',
        line=dict(color='#ff4d4d', width=2, dash='dash')
    ))
    
    fig.update_layout(
        title=dict(text="Évolution du Stock dans le Temps", font=dict(size=20, color="white")),
        xaxis_title="Mois",
        yaxis_title="Quantité en Stock",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )
    
    return fig

def style_table_principal(df, point_commande):
    """Applique une stylisation conditionnelle au tableau principal."""
    def highlight_row(row):
        styles = [''] * len(row)
        try:
            # Récupération sécurisée des index
            idx_stock = df.columns.get_loc("Stock rectifié en fonction des entrées")
            idx_cmd = df.columns.get_loc("Commande (Quantité)")
            idx_liv = df.columns.get_loc("Livraison")
            
            # Vérifier la présence d'une livraison pour surligner toute la ligne
            liv_val = str(row.iloc[idx_liv])
            has_livraison = liv_val not in ["0", "-", ""]
            
            if has_livraison:
                styles = ['background-color: rgba(0, 180, 216, 0.08);'] * len(row)
            
            # 1. Règle : Rupture ou point de commande atteint
            stock_val = float(row.iloc[idx_stock]) if str(row.iloc[idx_stock]) not in ["-", ""] else 0
            if stock_val <= 0:
                styles[idx_stock] = 'background-color: rgba(255, 77, 77, 0.2); color: #ff4d4d; font-weight: bold;'
            elif stock_val <= point_commande:
                styles[idx_stock] = 'background-color: rgba(255, 165, 0, 0.2); color: #ffa500; font-weight: bold;'
                
            # 2. Règle : Commande déclenchée
            cmd_val = str(row.iloc[idx_cmd])
            if cmd_val not in ["0", "-", ""]:
                styles[idx_cmd] = 'background-color: rgba(0, 255, 0, 0.15); color: #00ff00; font-weight: bold;'
                
            # 3. Règle : Livraison reçue (mise en évidence plus forte de la cellule)
            if has_livraison:
                styles[idx_liv] = 'background-color: rgba(0, 180, 216, 0.25); color: #00b4d8; font-weight: bold;'
        except Exception:
            pass
        return styles

    return df.style.apply(highlight_row, axis=1)

def style_table_synthese(df, point_commande):
    """Applique une stylisation conditionnelle au tableau de synthèse."""
    def highlight_col(col):
        styles = [''] * len(col)
        
        # Vérifier s'il y a une livraison dans le mois pour surligner toute la colonne
        has_livraison = False
        try:
            liv_val = str(col.get("Livraison", "0"))
            if liv_val not in ["0", "-", ""]:
                has_livraison = True
        except:
            pass
            
        if has_livraison:
            styles = ['background-color: rgba(0, 180, 216, 0.08);'] * len(col)
            
        for i, (index_name, val) in enumerate(col.items()):
            try:
                num_val = float(val) if str(val) not in ["-", ""] else 0
                if index_name == "Stock":
                    if num_val <= 0:
                        styles[i] = 'background-color: rgba(255, 77, 77, 0.2); color: #ff4d4d; font-weight: bold;'
                    elif num_val <= point_commande:
                        styles[i] = 'background-color: rgba(255, 165, 0, 0.2); color: #ffa500; font-weight: bold;'
                elif index_name == "Commande" and num_val > 0:
                    styles[i] = 'background-color: rgba(0, 255, 0, 0.15); color: #00ff00; font-weight: bold;'
                elif index_name == "Livraison" and num_val > 0:
                    styles[i] = 'background-color: rgba(0, 180, 216, 0.25); color: #00b4d8; font-weight: bold;'
            except:
                pass
        return styles
        
    return df.style.apply(highlight_col)

def page_historique():
    st.title("Historique des Simulations")
    st.markdown("Retrouvez ici toutes vos simulations passées enregistrées dans la base de données. Cliquez sur une simulation pour en voir le détail complet.")
    st.markdown("---")

    rows = load_simulations()
    
    if not rows:
        st.info("Aucune simulation enregistrée pour le moment.")
        return

    for row in rows:
        # Formatage de la date de création
        btn_label = f"Simulation N°{row.id}"
        if hasattr(row, "date_creation") and row.date_creation:
            if hasattr(row.date_creation, "strftime"):
                # Si psycopg2 renvoie un objet datetime
                date_str = row.date_creation.strftime("%d-%m-%Y à %H:%M:%S")
            else:
                # Si c'est une string (fallback)
                try:
                    from datetime import datetime
                    # On retire les éventuelles millisecondes
                    clean_date = str(row.date_creation).split(".")[0]
                    dt = datetime.strptime(clean_date, "%Y-%m-%d %H:%M:%S")
                    date_str = dt.strftime("%d-%m-%Y à %H:%M:%S")
                except:
                    date_str = str(row.date_creation)
            btn_label = f"Simulation du {date_str}"

        # Design amélioré avec st.expander + tabs
        with st.expander(f"📁 {btn_label}"):
            tab_vue, tab_edit = st.tabs(["Visualisation", "Modifier"])

            # ─── Onglet Visualisation ───────────────────────────────────────────
            with tab_vue:
                col1, col2, col3, col4 = st.columns(4)
                q_val = getattr(row, 'q', getattr(row, 'Q', 'N/A'))
                n_val = getattr(row, 'n', getattr(row, 'N', 'N/A'))
                col1.metric("Quantité économique (Q)", f"{q_val} unités")
                col2.metric("Point de commande", f"{row.point_commande} unités")
                col3.metric("Commandes/an (N)", f"{n_val}")
                col4.metric("Période", f"{row.periode} mois")

                st.markdown("---")
                df_main, df_synth = json_to_df(row.df_main, row.df_synth)

                try:
                    stock_secu_qte = row.stock_secu_mois * row.conso_mensuelle
                    fig_dyn = generate_graph(df_synth, stock_secu_qte)
                    st.plotly_chart(fig_dyn, use_container_width=True)
                except Exception:
                    pass

                main_h = 38 + 35 * len(df_main)
                st.write("#### Tableau Principal")
                st.dataframe(style_table_principal(df_main, row.point_commande), use_container_width=True, hide_index=True, height=main_h)
                st.write("#### Tableau Synthèse")
                st.dataframe(style_table_synthese(df_synth, row.point_commande), use_container_width=True)

                st.markdown("<br>", unsafe_allow_html=True)
                col_spacer, col_del = st.columns([7, 3])
                with col_del:
                    if st.button(" Supprimer cette sauvegarde", key=f"del_btn_{row.id}", type="primary", use_container_width=True, help="Attention, suppression définitive"):
                        delete_simulation(row.id)
                        st.rerun()

            # ─── Onglet Modification ────────────────────────────────────────────
            with tab_edit:
                st.markdown("#### Modifier les paramètres de la simulation")
                st.info("Modifiez les paramètres ci-dessous, ajustez les consommations mensuelles, puis cliquez sur **Mettre à jour** pour sauvegarder vos modifications.")

                ec1, ec2 = st.columns(2)
                with ec1:
                    e_conso_ann = st.number_input("Consommation annuelle", value=float(row.conso_annuelle), min_value=0.0, step=100.0, key=f"e_ca_{row.id}")
                    e_prix = st.number_input("Prix unitaire (Ariary)", value=float(row.prix_unitaire), min_value=0.0, step=1000.0, key=f"e_pu_{row.id}")
                    e_delai = st.number_input("Délai d'appro. (mois)", value=float(row.delai_appro), min_value=0.0, step=0.1, key=f"e_da_{row.id}")
                with ec2:
                    e_conso_men = st.number_input("Consommation mensuelle", value=float(row.conso_mensuelle), min_value=0.0, step=10.0, key=f"e_cm_{row.id}")
                    e_taux = st.number_input("Taux de possession", value=float(row.taux_possession), min_value=0.01, step=0.01, format="%.2f", key=f"e_tp_{row.id}")
                    e_secu = st.number_input("Stock de sécurité (mois)", value=float(row.stock_secu_mois), min_value=0.0, step=0.1, key=f"e_ss_{row.id}")

                e_cout_pass = st.number_input("Coût de passation", value=float(row.cout_passation), min_value=0.0, step=1000.0, key=f"e_cp_{row.id}")

                st.markdown("**Consommations mensuelles (détail)**")
                df_main_edit, _ = json_to_df(row.df_main, row.df_synth)
                df_conso_edit = df_main_edit[["Période", "Consommation"]].copy()
                df_conso_edit["Consommation"] = pd.to_numeric(df_conso_edit["Consommation"], errors="coerce").fillna(0)
                conso_h = 38 + 35 * len(df_conso_edit)
                df_conso_updated = st.data_editor(
                    df_conso_edit, use_container_width=True, hide_index=True, height=conso_h,
                    column_config={
                        "Période": st.column_config.TextColumn("Mois", disabled=True),
                        "Consommation": st.column_config.NumberColumn("Consommation Prévue", min_value=0, step=10, required=True)
                    }, key=f"e_conso_editor_{row.id}"
                )

                st.markdown("<br>", unsafe_allow_html=True)
                _, col_upd = st.columns([6, 4])
                with col_upd:
                    st.markdown('<div class="update-btn">', unsafe_allow_html=True)
                    if st.button("Mettre à jour la simulation", key=f"upd_btn_{row.id}", use_container_width=True):
                        eN, eQ, eperiode, epoint = calcul_stock(
                            e_conso_ann, e_conso_men, e_prix, e_cout_pass, e_taux, e_delai, e_secu
                        )
                        e_stock_initial = df_main_edit["Stock rectifié en fonction des entrées"].iloc[0] if len(df_main_edit) else 0
                        try:
                            e_stock_initial = int(str(e_stock_initial).replace("-", "0") or 0)
                        except:
                            e_stock_initial = 0

                        new_df_main, new_df_synth = generate_table_dynamique(eQ, epoint, e_delai, e_stock_initial, df_conso_updated)
                        update_simulation(
                            row.id,
                            params={"conso_annuelle": e_conso_ann, "conso_mensuelle": e_conso_men,
                                    "prix_unitaire": e_prix, "cout_passation": e_cout_pass,
                                    "taux_possession": e_taux, "delai_appro": e_delai,
                                    "stock_secu_mois": e_secu},
                            results={"N": eN, "Q": eQ, "periode": eperiode, "point_commande": epoint},
                            df_main=new_df_main,
                            df_synth=new_df_synth
                        )
                        st.success("✅ Simulation mise à jour avec succès !")
                        st.rerun()
                    st.markdown('</div>', unsafe_allow_html=True)

# --- APPLICATION PRINCIPALE ---

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Aller à :", ["Nouvelle Simulation", "Historique des Simulations"])
    st.sidebar.markdown("---")
    
    if page == "Nouvelle Simulation":
        page_nouvelle_simulation()
    elif page == "Historique des Simulations":
        page_historique()

def page_nouvelle_simulation():
    st.title("Gestion de Stock")
    st.markdown("Cette application propose une version dynamique interactive et intelligente de calculs de détermination de consommation réguliére d'une entreprise.")
    
    # --- SIDEBAR ---
    st.sidebar.header("Paramètres d'Entrée")
    
    conso_annuelle = st.sidebar.number_input("Consommation annuelle", value=None, min_value=0, step=100, placeholder="Ex: 1200")
    conso_mensuelle = st.sidebar.number_input("Consommation mensuelle", value=None, min_value=0, step=10, placeholder="Ex: 100")
    prix_unitaire = st.sidebar.number_input("Prix unitaire (Ariary)", value=None, min_value=0.0, step=1000.0, placeholder="Ex: 16000")
    cout_passation = st.sidebar.number_input("Coût de passation", value=None, min_value=0.0, step=1000.0, placeholder="Ex: 60000")
    taux_possession = st.sidebar.number_input("Taux de possession", value=None, min_value=0.01, step=0.01, format="%.2f", placeholder="Ex: 0.10")
    delai_appro = st.sidebar.number_input("Délai d'appro. (mois)", value=None, min_value=0.0, step=0.1, placeholder="Ex: 1.5")
    stock_secu_mois = st.sidebar.number_input("Stock de sécurité (mois)", value=None, min_value=0.0, step=0.1, placeholder="Ex: 0.5")
    
    st.sidebar.markdown("---")
    st.sidebar.header("Paramètres de Simulation")
    horizon = st.sidebar.number_input("Horizon de simulation (mois)", value=14, min_value=1, max_value=60)
    
    mois_noms_complets = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    mois_debut = st.sidebar.selectbox("Mois de début", mois_noms_complets, index=10) # 10 = Novembre
    stock_initial = st.sidebar.number_input("Stock initial", value=0, step=10)
    
    # --- VÉRIFICATION DES ENTRÉES ---
    params = [conso_annuelle, conso_mensuelle, prix_unitaire, cout_passation, taux_possession, delai_appro, stock_secu_mois]
    if any(p is None for p in params):
        st.info("← **Action Requise :** Veuillez renseigner tous les paramètres d'entrée dans la barre latérale gauche pour lancer les calculs et afficher la simulation.")
        return
        
    if prix_unitaire <= 0 or taux_possession <= 0:
        st.error("Le prix unitaire et le taux de possession doivent être strictement supérieurs à 0 pour le calcul de Wilson.")
        return
        
    # --- CALCULS ---
    N, Q, periode, point_commande = calcul_stock(
        conso_annuelle, conso_mensuelle, prix_unitaire, 
        cout_passation, taux_possession, delai_appro, stock_secu_mois
    )
    stock_secu_qte = stock_secu_mois * conso_mensuelle
    
    # --- RESULTATS / KPIs ---
    st.header("Indicateurs Clés de Performance (KPI)")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="Nombre de commandes (N)", value=f"{N} / an")
    with col2:
        st.metric(label="Quantité économique (Q)", value=f"{Q} unités")
    with col3:
        st.metric(label="Période entre commandes", value=f"{periode} mois")
    with col4:
        st.metric(label="Point de commande", value=f"{point_commande} unités")

    st.markdown("---")

    st.subheader("Tableau de consommation")
    st.info(" **Éditez directement la colonne 'Consommation'** dans le tableau ci-dessous pour que l'algorithme intelligent (basé sur le Point de Commande) s'adapte en temps réel !")
    
    # Génération de la liste dynamique des mois
    idx_debut = mois_noms_complets.index(mois_debut)
    liste_mois = [mois_noms_complets[(idx_debut + i) % 12] for i in range(horizon)]
    
    # Dataframe pour l'éditeur interactif
    df_conso_init = pd.DataFrame({
        "Période": liste_mois,
        "Consommation": [conso_mensuelle] * horizon
    })
    
    # Hauteur dynamique : 38px d'en-tête + 35px par ligne
    table_height = 38 + 35 * len(df_conso_init)
    df_conso_edite = st.data_editor(
        df_conso_init, 
        use_container_width=True,
        hide_index=True,
        height=table_height,
        column_config={
            "Période": st.column_config.TextColumn("Mois", disabled=True),
            "Consommation": st.column_config.NumberColumn("Consommation Prévue", min_value=0, step=10, required=True)
        }
    )
    
    df_dyn_main, df_dyn_synth = generate_table_dynamique(Q, point_commande, delai_appro, stock_initial, df_conso_edite)


    st.subheader("Évolution des stocks")
    fig_dyn = generate_graph(df_dyn_synth, stock_secu_qte)
    st.plotly_chart(fig_dyn, use_container_width=True)
    
    st.subheader("Tableau Principal")
    main_height = 38 + 35 * len(df_dyn_main)
    st.dataframe(style_table_principal(df_dyn_main, point_commande), use_container_width=True, hide_index=True, height=main_height)
    
    st.subheader("Tableau de Synthèse")
    st.dataframe(style_table_synthese(df_dyn_synth, point_commande), use_container_width=True)

    
    # Export
    buffer_dyn = BytesIO()
    with pd.ExcelWriter(buffer_dyn, engine='openpyxl') as writer:
        df_dyn_main.to_excel(writer, sheet_name='Principal_Dyn', index=False)
        df_dyn_synth.to_excel(writer, sheet_name='Synthèse_Dyn')
    
    st.download_button(
        label="Exporter vers Excel",
        data=buffer_dyn.getvalue(),
        file_name="gestion_stock_dynamique.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    if st.button("✔ Sauvegarder cette simulation"):
        save_simulation(
            params={
                "conso_annuelle": conso_annuelle,
                "conso_mensuelle": conso_mensuelle,
                "prix_unitaire": prix_unitaire,
                "cout_passation": cout_passation,
                "taux_possession": taux_possession,
                "delai_appro": delai_appro,
                "stock_secu_mois": stock_secu_mois
            },
            results={
                "N": N,
                "Q": Q,
                "periode": periode,
                "point_commande": point_commande
            },
            df_main=df_dyn_main,
            df_synth=df_dyn_synth
        )

        st.success("✔ Simulation sauvegardée !")
        import streamlit.components.v1 as components
        components.html(
            """
            <script>
            setTimeout(function() {
                var alerts = window.parent.document.querySelectorAll('[data-testid="stAlert"]');
                alerts.forEach(function(a) {
                    if (a.innerText.includes('Simulation sauvegardée')) {
                        a.style.display = 'none';
                    }
                });
            }, 5000);
            </script>
            """,
            height=0,
            width=0,
        )

if __name__ == "__main__":
    main()