# Startup patents and survival

This project studies whether the ownership of patent portfolios influences the survival of startups.

The analysis focuses on French startups and uses patent data from public patent databases (INPI / Patstat).
The objective is to assess the relationship between patent activity and startup survival using econometric models.

This repository contains data collection, name-matching algorithms, feature construction, and econometric analysis.


## Project structure


startup-patents-survival/
├── src/            # Python scripts
├── data/
│   ├── raw/        # Raw data (ignored by git)
│   └── processed/  # Processed data (ignored by git)
├── notebooks/      # Exploration notebooks
├── requirements.txt
└── README.md


## Installation

This project uses Python 3.

Install the required Python packages with:

pip install -r requirements.txt


## Usage

### Scrape FrenchCleantech companies by category

The main scraping script is `scrape_frenchcleantech.py`.

Example command: python src/scrape_frenchcleantech.py --category-slug energy-generation --max-page 5


This command:

* scrapes companies from the selected FrenchCleantech category,
* normalizes company names,
* saves the results into the `data/raw/` directory.

Two CSV files are generated:

* `frenchcleantech_<category>.csv`
* `frenchcleantech_<category>_companies.csv`

## Data management

Raw and processed data files are intentionally excluded from version control and must be generated locally.