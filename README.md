# Sorties 13

Site statique qui regroupe les sorties des Bouches-du-Rhône (sites des villes et MyProvence) et les trie selon trois profils : famille, jeune adulte et adulte, senior.

## Contenu

- `index.html` : le site (aucune dépendance, il lit `data/events.json`)
- `data/events.json` : les sorties (au départ, des données de démonstration)
- `scripts/update.py` : collecte les pages, fait extraire et classer les sorties par Claude
- `scripts/sources.json` : les sites à interroger
- `.github/workflows/update.yml` : lance la mise à jour chaque jour

## Tester en local

    python -m http.server 8000

Puis ouvrir http://localhost:8000 (le fichier ne se charge pas en double-cliquant dessus).

Pour lancer une vraie mise à jour :

    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...
    python scripts/update.py

## Mise en ligne avec mise à jour automatique

1. Créez un dépôt GitHub et envoyez-y ce dossier.
2. Dans Settings > Secrets and variables > Actions, ajoutez `ANTHROPIC_API_KEY`.
3. Dans Settings > Pages, publiez la branche `main` (racine).
4. Dans l'onglet Actions, lancez une première fois « Mise à jour quotidienne des sorties ». Ensuite elle tourne seule chaque jour.

## Points à vérifier

- **Adresses des sources** : `sources.json` contient les pages d'accueil. Le script suit les liens « agenda », « événements », etc., mais vérifiez le résultat de la première exécution et ajoutez directement les URL d'agenda qui manquent.
- **Droits d'utilisation** : relisez les conditions d'utilisation de MyProvence et des villes. Le script respecte `robots.txt`, ne publie que de courts résumés reformulés et renvoie vers la source, mais certains sites interdisent la réutilisation automatisée. Une demande d'accès à leurs données ouvertes (open data) est souvent plus sûre.
- **Fiabilité** : le résumé et le classement par profil sont produits par IA et peuvent se tromper. Le pied de page invite à vérifier chez l'organisateur.
- **Coût** : quelques dizaines d'appels à l'API par jour. Changez de modèle avec la variable `ANTHROPIC_MODEL` si besoin.
- **Sites dynamiques** : si une ville charge son agenda en JavaScript, la page paraîtra vide au script. Il faudra alors utiliser son flux ou son API, ou ajouter un navigateur automatisé.
