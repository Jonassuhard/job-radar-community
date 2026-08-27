# Confidentialite

## Local par defaut

Job Radar enregistre ses donnees dans les repertoires locaux de la personne qui
l'execute. L'API est liee a `127.0.0.1` par defaut. Le projet n'inclut aucun
compte, telemetrie, synchronisation cloud ou service de candidature.

Le mode demo est synthetique. Les entreprises, offres et coordonnees qu'il
contient sont fictives.

## Ce qui ne doit pas entrer dans le projet public

Ne joins jamais un CV, une lettre, une candidature, une adresse personnelle,
un numero de telephone, des cookies de session, des jetons API, des mots de
passe, des captures de navigateur authentifie ou une base SQLite dans une Issue,
une Pull Request, une discussion ou un fichier suivi par Git.

Les secrets sont lus uniquement depuis les variables d'environnement. Les
fichiers `.env`, bases locales et artefacts de test sont ignores par Git; cela
n'est pas une raison de les publier ailleurs.

## Conservation et suppression

Tu controles les fichiers de configuration et la base locale. Arrete le serveur
puis supprime le repertoire de donnees que tu as choisi, par exemple
`.job-radar/` dans le demarrage rapide. Sauvegarde ou exporte ce que tu veux
conserver avant suppression.

Pour un probleme de securite ou une exposition de donnees, utilise le canal
decrit dans [SECURITY.md](../SECURITY.md), sans publier la donnee sensible.
