Les commandes Anaconda Prompt :

cd chemin
→ tu te places dans le dossier du projet pour exécuter les scripts.

python src\scrape_frenchcleantech_all.py --max-page 0 --sleep 0.6
→ scrape toutes les entreprises du site FrenchCleantech (pages) et génère un CSV brut dans data/raw/.

python -c "import pandas as pd; df=pd.read_csv('data/raw/frenchcleantech_all_companies.csv'); print(df.shape); print(df.columns.tolist()); print(df.head(3))"
→ vérifie rapidement (shape / colonnes / premières lignes) que le scraping a bien produit un fichier cohérent.

python src\build_master_dataset.py
→ nettoie/structure la base brute pour créer un master prêt à enrichissement.

python src\lookup_siren.py --input data\processed\frenchcleantech_master.csv --output data\processed\frenchcleantech_master_siren.csv --sleep 0.3 --limit 5
→ pour chaque startup, interroge l’API publique recherche-entreprises.api.gouv.fr pour retrouver un SIREN (clé pivot entreprise).

python src\inpi_rne_survival.py --input data\processed\frenchcleantech_master_siren.csv --output data\processed\frenchcleantech_master_rne.csv
→ pour chaque SIREN trouvé, interroge INPI/RNE pour récupérer des infos admin (statut, création, cessation) et dériver la variable survival.

python src\inpi_pi_patents_portfolio.py --input data\processed\frenchcleantech_master_rne.csv --output data\processed\frenchcleantech_master_rne_patents.csv --sleep 2.0 --checkpoint-every 25 --resume
→ pour chaque SIREN, interroge INPI PI pour récupérer patents_total, en sauvegardant régulièrement et en pouvant reprendre après quota/erreur.

python src\build_final_dataset.py
→ fusion finale (master_rne + patents checkpoint), nettoyage des colonnes, calcul has_patent, création patents_status, export final dans data/raw/.

