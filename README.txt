TRÉSORS SPIRITUELS — PROTOTYPE VISUEL INTERACTIF

## Pour voir l’application

Décompresse le ZIP, puis double-clique sur index.html. L’aperçu s’ouvre avec les 30 articles
déjà récupérés sur le site. Rien à installer pour le consulter. Ces articles correspondent à
la synchronisation du 19 novembre 2026; cette ouverture seule ne relance pas la collecte.

Fonctions démontrées : accueil, rubriques, recherche parmi les 30 articles inclus,
lecture d’article, favoris enregistrés sur l’appareil et partage du lien d’origine.

## Synchronisation automatique hebdomadaire — préparation incluse

Le fichier `.github/workflows/sync-weekly.yml` est prêt à lancer le synchroniseur chaque samedi
à 02:20 (heure de Nouvelle-Calédonie), après les publications du vendredi. Il récupérera au plus
30 fiches complètes par semaine et publiera uniquement le catalogue JSON et son état pour qu’une
future app mobile puisse les lire. Il ne publiera pas le prototype web. Le premier essai réel a
parcouru 261 fiches listées dans 11 rubriques et récupéré 30 articles complets sans erreur.

Pour l’activer, il faudra :
1. Créer un dépôt **public** sur GitHub et y mettre le contenu de ce dossier.
2. Dans `Settings` → `Pages`, choisir `GitHub Actions` comme source.
3. Dans `Actions`, lancer une fois `Synchronisation hebdomadaire Webador`.

**Attention :** le dépôt GitHub et le catalogue hébergé seront publics. Les articles sont déjà
visibles sur Webador; le code du projet sera aussi visible dans le dépôt. Le synchroniseur ne
modifie pas le site Webador. GitHub Actions et Pages sont gratuits pour un dépôt public selon les
limites de GitHub. Les horaires peuvent être retardés, et GitHub peut désactiver le planning si
le dépôt public reste inactif pendant 60 jours.

Cette publication hébergerait seulement les fichiers JSON destinés à l’application. Elle ne
créerait pas encore l’application native à installer sur iPhone ou Android. Aucun hébergement
n’est activé à ce jour.

Le visuel du prototype d'origine a été conservé. Les 30 articles du catalogue sont issus des
pages publiques et synchronisés le 19 novembre 2026. Les images restent hébergées par Webador.
Webador indique ne pas prendre en charge les connexions API personnalisées via le code HTML :
https://help.webador.com/hc/en-us/articles/29426708302481-Add-custom-HTML-code-to-your-website
