# Verification d'une release

Une preuve de release utilise deux commits. Ce protocole evite de presenter des
resultats comme valides pour un code qui aurait change apres leur execution.

## 1. Commit candidat

Le premier commit contient le produit, les tests, la documentation et un fichier
`docs/verification/vX.Y.Z-beta.N.json` minimal :

- `schema_version` vaut `2` ;
- `status` vaut `pending_commit_pin` ;
- `tested_product_commit`, `test_harness_commit` et `verified_at` valent `null` ;
- `publication` vaut `{"status": "not_observed", "observed_at": null}` ;
- aucun resultat de test, d'audit ou de capture n'est declare.

Le hash de ce commit devient l'identifiant immuable du candidat a verifier.
Le meme commit contient le contrat versionne
`docs/verification/vX.Y.Z-beta.N-contract.json`. Il fixe les cles autorisees,
les versions, les nombres de tests, les audits, OpenAPI, les captures et les
limites attendues. Le commit de preuve ne peut pas modifier ce contrat.

## 2. Verification fraiche

Tous les controles annonces dans le futur enregistrement final sont executes sur
ce commit precis. Les resultats ne sont pas recopies depuis une ancienne release.
L'observation de publication est egalement refaite et horodatee.

Le test du demarrage depuis une archive utilise `build_candidate_archive(...)`.
Cette fonction produit uniquement un staging audite, un ZIP et son checksum. Elle
accepte le statut `pending_commit_pin`, n'ecrit jamais d'attestation et n'est pas
exposee par la CLI de publication.

## 3. Commit de preuve

Le second commit modifie uniquement le JSON de verification. Il contient :

- `status: "local_candidate_verified"` ;
- le meme hash existant dans `tested_product_commit` et
  `test_harness_commit` ;
- un `verified_at` ISO 8601 avec fuseau horaire ;
- `publication.status` egal a `not_published` ;
- `publication.observed_at` en ISO 8601 avec fuseau horaire ;
- les resultats et limites effectivement observes.

Pour un candidat local, `publication.status` vaut obligatoirement
`not_published`. `publication` est une observation horodatee, pas un etat suppose permanent. Le
champ booleen historique `github_published` n'est plus accepte.

## 4. Construction

Le builder final refuse la release si :

- le schema n'est pas la version 2 ;
- le statut est encore `pending_commit_pin` ;
- les deux commits testes different, n'existent pas ou ne sont pas des ancetres ;
- un horodatage n'a pas de fuseau ;
- un horodatage est dans le futur ;
- un champ, un resultat ou une capture differe du contrat versionne ;
- le diff entre le commit teste et le commit de preuve contient autre chose que
  le JSON de verification de la release.

La commande de construction appelle uniquement `build_release(...)`. Elle produit
le ZIP, son SHA-256 et une attestation externe. L'attestation recalcule le contenu
du ZIP et reprend les identifiants de commit, les horodatages, l'observation de
publication et les controles du JSON.

L'attestation separe deux categories :

- `builder_observations` contient les valeurs recalculees pendant la construction
  (attestation generee, archive, OpenAPI, hash du record et hash du contrat) ;
- `declared_verification` contient les resultats du record qui correspondent
  exactement a la matrice versionnee.

Le builder ne pretend pas avoir execute les tests et audits de
`declared_verification`. Il prouve leur integrite et leur conformite au contrat ;
leur execution reste celle du protocole de verification fraiche.
La matrice de T ne revendique donc pas l'attestation finale : elle ne conserve
que les deux constructions deterministes de l'archive candidate. L'attestation
est observee et declaree par `build_release(...)` au moment de E.

Apres la creation du SBOM, du wheel et du sdist,
`finalize_release_attestation.py` ajoute atomiquement `published_assets`. Cette
section lie le ZIP source, son checksum, le SBOM, le wheel et le sdist par leur
nom exact, leur type, leur taille et leur SHA-256. L'attestation ne tente pas de
contenir son propre hash, ce qui serait circulaire.

Avant l'appel a GitHub, `publish_release.sh` recalcule ces cinq empreintes,
refuse tout fichier absent ou supplementaire et verifie que le tag existe dans
le checkout et sur `origin`, au commit indique par l'attestation. La publication
utilise `gh release create --verify-tag` : GitHub ne peut donc pas fabriquer un
tag manquant depuis la branche par defaut.
