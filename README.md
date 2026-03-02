# Startup Survival & Patents

Projet de M2 – Analyse économétrique du lien entre innovation (brevets) et survie des startups French Cleantech.

## Objectif

Construire un pipeline complet permettant de :

1. Scraper les startups depuis French Cleantech 
2. Associer un SIREN via l’API publique recherche-entreprises 
3. Récupérer les informations administratives INPI (RNE) 
4. Extraire les portefeuilles de brevets via l’API INPI PI 
5. Construire une base finale prête pour l’analyse économétrique 

---

## Structure du projet

```
data/
  raw/
  processed/

src/
  scrape_frenchcleantech_all.py
  build_master_dataset.py
  lookup_siren.py
  inpi_rne_survival.py
  inpi_pi_patents_portfolio.py
  build_final_dataset.py

notebooks/
  Projet_tuteuré_code_analyse.ipynb
```

---

## Prérequis

- Python 3.10+
- Compte INPI (RNE + API PI)
- Accès API activé

Installer les dépendances :

```bash
pip install -r requirements.txt
```

---

## Configuration

Créer un fichier `.env` à la racine du projet :

```
INPI_EMAIL=your_email
INPI_PASSWORD=your_password

INPI_PI_EMAIL=your_email
INPI_PI_PASSWORD=your_password
```

---

## Exécution du pipeline

Depuis le dossier du projet :

```bash
cd C:\Users\...\startup-patents-survival
```

1. Scraping

```bash
python src\scrape_frenchcleantech_all.py --max-page 0 --sleep 0.6
```

2. Construction master

```bash
python src\build_master_dataset.py
```

3. Recherche SIREN

```bash
python src\lookup_siren.py --input data\processed\frenchcleantech_master.csv --output data\processed\frenchcleantech_master_siren.csv
```

4. Enrichissement RNE

```bash
python src\inpi_rne_survival.py --input data\processed\frenchcleantech_master_siren.csv --output data\processed\frenchcleantech_master_rne.csv
```

5. Extraction brevets

```bash
python src\inpi_pi_patents_portfolio.py --input data\processed\frenchcleantech_master_rne.csv --output data\processed\frenchcleantech_master_rne_patents.csv --sleep 2.0 --checkpoint-every 25 --resume
```

6. Base finale

```bash
python src\build_final_dataset.py
```

---

## Reproductibilité

Les dossiers `data/raw` et `data/processed` sont volontairement exclus du dépôt. 
La base peut être reconstruite intégralement en exécutant le pipeline ci-dessus avec des identifiants INPI valides.

---

Projet réalisé dans le cadre du Master 2 – CMI D3S IES
