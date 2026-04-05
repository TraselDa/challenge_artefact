# Schema Reference — EDAN 2025 Election Results Database

> Ce fichier est la SEULE source de vérité pour la génération SQL.
> Ne JAMAIS inventer de colonnes ou tables non listées ici.

---

## Scope — quelle vue utiliser selon la question

| Type de question | Scope | Vue |
|-----------------|-------|-----|
| "Combien de sièges a le RHDP ?" | National → parti | `vw_results_by_party` |
| "Quel parti a gagné à Abidjan ?" | Région → parti | `vw_party_scores_by_region` |
| "Classement des partis dans la région X" | Région → parti | `vw_party_scores_by_region` |
| "Qui a gagné dans la circonscription 5 ?" | Circonscription | `vw_winners` ou `vw_results_by_circonscription` |
| "Classement des candidats dans la circo X" | Circo → candidat | `vw_candidates_ranked_by_circonscription` |
| "Taux de participation par région" | Régions | `vw_results_by_region` |
| "Région avec le plus fort taux d'abstention" | Régions | `vw_results_by_region` |
| "Participation/abstention dans la circo X" | Circonscription | `vw_turnout` |
| "Élections les plus serrées / disputées" | National | `vw_close_races` |
| "Marge de victoire dans la circo X" | Circonscription | `vw_results_by_circonscription` |
| "Totaux nationaux" | National | `summary_national` |

⚠️ `vw_results_by_party` n'a PAS de colonne `region` — elle est nationale uniquement.
Pour "quel parti a gagné à [région/ville]" → utiliser `vw_party_scores_by_region`.

---

## Tables disponibles

### 1. `results` — Table principale (1 ligne = 1 candidat dans 1 circonscription)

| Colonne | Type | Description | Exemples de valeurs |
|---------|------|-------------|---------------------|
| `region` | TEXT | Région administrative | "AGNEBY-TIASSA", "ABIDJAN", "PORO", "HAUT-SASSANDRA" |
| `numero_circonscription` | INTEGER | Numéro unique de la circonscription | 1, 2, 3, ..., 255 |
| `circonscription` | TEXT | Nom complet (communes/sous-préfectures) | "AGBOVILLE COMMUNE", "AZAGUIE COMMUNE ET SOUS-PREFECTURE" |
| `nb_bureaux_vote` | INTEGER | Nombre de bureaux de vote | 133, 44, 72 |
| `inscrits` | INTEGER | Électeurs inscrits | 48710, 15515, 23466 |
| `votants` | INTEGER | Nombre de votants | 12821, 5174, 7650 |
| `taux_participation` | REAL | Taux de participation (en %) | 26.32, 33.35, 32.60 |
| `bulletins_nuls` | INTEGER | Bulletins nuls | 317, 73, 241 |
| `suffrages_exprimes` | INTEGER | Suffrages valablement exprimés | 12504, 5101, 7409 |
| `bulletins_blancs` | INTEGER | Nombre de bulletins blancs | 81, 24, 49 |
| `bulletins_blancs_pct` | REAL | % bulletins blancs | 0.65, 0.47, 0.66 |
| `parti` | TEXT | Parti politique ou "INDEPENDANT" | "RHDP", "INDEPENDANT", "PDCI-RDA", "FPI", "ADCI", "MGC" |
| `candidat` | TEXT | Nom complet du candidat (MAJUSCULES) | "DIMBA N'GOU PIERRE", "KOFFI AKA CHARLES", "ALAIN EKISSI" |
| `scores` | INTEGER | Nombre de voix obtenues | 10675, 9078, 1673 |
| `score_pct` | REAL | % des suffrages exprimés | 85.37, 66.35, 32.80 |
| `elu` | BOOLEAN | TRUE si le candidat est élu | TRUE, FALSE |
| `source_page` | INTEGER | Numéro de page PDF source (1-indexé) | 1, 2, 3, ... 35 |

**Nombre de lignes :** ~2500-3500 (tous les candidats de toutes les circonscriptions)

---

### 2. `summary_national` — Résumé national (1 seule ligne)

| Colonne | Type | Valeur |
|---------|------|--------|
| `nb_bureaux_vote` | INTEGER | 25338 |
| `inscrits` | INTEGER | 8597092 |
| `votants` | INTEGER | 3012094 |
| `taux_participation` | REAL | 35.04 |
| `taux_abstention` | REAL | 64.96 |
| `bulletins_nuls` | INTEGER | 68525 |
| `suffrages_exprimes` | INTEGER | 2943569 |
| `bulletins_blancs` | INTEGER | 29578 |
| `bulletins_blancs_pct` | REAL | 1.00 |
| `total_scores` | INTEGER | 2913991 |

---

## Vues disponibles

### 3. `vw_winners` — Uniquement les candidats élus

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Région |
| `numero_circonscription` | INTEGER | Numéro de circonscription |
| `circonscription` | TEXT | Nom de la circonscription |
| `parti` | TEXT | Parti de l'élu |
| `candidat` | TEXT | Nom de l'élu |
| `scores` | INTEGER | Voix obtenues |
| `score_pct` | REAL | % des suffrages |
| `nb_bureaux_vote` | INTEGER | Bureaux de vote dans la circonscription |
| `inscrits` | INTEGER | Électeurs inscrits dans la circonscription |
| `votants` | INTEGER | Votants dans la circonscription |
| `taux_participation` | REAL | Taux de participation dans la circonscription (%) |
| `bulletins_nuls` | INTEGER | Bulletins nuls |
| `suffrages_exprimes` | INTEGER | Suffrages exprimés |
| `bulletins_blancs` | INTEGER | Bulletins blancs |
| `bulletins_blancs_pct` | REAL | % bulletins blancs |

**Usage :** Questions sur "qui a gagné", "les élus", "les vainqueurs", "sièges remportés", "avec quel taux de participation".

### 4. `vw_turnout` — Participation par circonscription (sans doublons candidats)

Colonnes : `region`, `numero_circonscription`, `circonscription`, `nb_bureaux_vote`, `inscrits`, `votants`, `taux_participation`, `taux_abstention`, `bulletins_nuls`, `bulletins_nuls_pct`, `suffrages_exprimes`, `bulletins_blancs`, `bulletins_blancs_pct`

**Usage :** Questions sur la "participation", "abstention", "taux", "inscrits", "votants", "bulletins nuls/blancs".

### 5. `vw_results_by_region` — Agrégation par région

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Nom de la région |
| `nb_circonscriptions` | INTEGER | Nombre de circonscriptions dans la région |
| `nb_sieges` | INTEGER | Nombre de sièges remportés |
| `total_nb_bureaux_vote` | INTEGER | Total bureaux de vote (somme des circonscriptions) |
| `total_inscrits` | INTEGER | Total électeurs inscrits |
| `total_votants` | INTEGER | Total votants |
| `taux_participation` | REAL | Taux de participation pondéré (total_votants / total_inscrits × 100) |
| `taux_abstention` | REAL | Taux d'abstention pondéré (100 - taux_participation) |
| `total_bulletins_nuls` | INTEGER | Total bulletins nuls |
| `total_suffrages_exprimes` | INTEGER | Total suffrages exprimés |
| `total_bulletins_blancs` | INTEGER | Total bulletins blancs |
| `bulletins_blancs_pct` | REAL | % bulletins blancs pondéré (total_bulletins_blancs / total_suffrages_exprimes × 100) |
| `nb_candidats` | INTEGER | Nombre total de candidats dans la région (toutes circonscriptions) |
| `bulletins_nuls_pct` | REAL | % bulletins nuls (total_bulletins_nuls / total_votants × 100) |

**Usage :** Questions "par région", "région avec le plus/moins de...", comparaisons régionales, taux de participation par région.

### 6. `vw_results_by_party` — Résumé par parti politique

| Colonne | Type | Description |
|---------|------|-------------|
| `parti` | TEXT | Nom du parti |
| `nb_candidats` | INTEGER | Nombre de candidats présentés |
| `total_scores` | INTEGER | Total des voix obtenues |
| `nb_sieges` | INTEGER | Sièges remportés |
| `taux_victoire` | REAL | % de sièges remportés sur l'ensemble des circonscriptions |
| `total_nb_bureaux_vote` | INTEGER | Total BV dans les circonscriptions où le parti était présent |
| `total_inscrits` | INTEGER | Total inscrits dans ces circonscriptions |
| `total_votants` | INTEGER | Total votants dans ces circonscriptions |
| `taux_participation` | REAL | Taux de participation pondéré dans les circonscriptions du parti (%) |
| `total_bulletins_nuls` | INTEGER | Total bulletins nuls |
| `total_suffrages_exprimes` | INTEGER | Total suffrages exprimés |
| `total_bulletins_blancs` | INTEGER | Total bulletins blancs |
| `bulletins_blancs_pct` | REAL | % bulletins blancs pondéré |

**Usage :** Questions NATIONALES sur les partis : "combien de sièges RHDP au total", "parti dominant au niveau national", classement des partis sur tout le pays.

⚠️ **NATIONAL UNIQUEMENT** — cette vue n'a PAS de colonne `region`. Ne jamais y ajouter `WHERE region = ...`. Pour les sièges/scores d'un parti dans une région → utiliser `vw_party_scores_by_region`.

### 7. `vw_results_by_circonscription` — Résumé par circonscription

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Région |
| `numero_circonscription` | INTEGER | Numéro unique |
| `circonscription` | TEXT | Nom |
| `nb_bureaux_vote` | INTEGER | Nombre de bureaux de vote |
| `inscrits` | INTEGER | Électeurs inscrits |
| `votants` | INTEGER | Votants |
| `taux_participation` | REAL | Taux de participation (%) |
| `taux_abstention` | REAL | Taux d'abstention (100 - taux_participation) |
| `bulletins_nuls` | INTEGER | Bulletins nuls |
| `suffrages_exprimes` | INTEGER | Suffrages exprimés |
| `bulletins_blancs` | INTEGER | Bulletins blancs |
| `bulletins_blancs_pct` | REAL | % bulletins blancs |
| `nb_candidats` | INTEGER | Nombre de candidats en lice |
| `elu_candidat` | TEXT | Nom du candidat élu |
| `elu_parti` | TEXT | Parti du candidat élu |
| `elu_scores` | INTEGER | Score du candidat élu |
| `elu_score_pct` | REAL | % du score de l'élu |
| `runner_up_scores` | INTEGER | Score du 2ème candidat (NULL si candidat unique) |
| `marge_victoire` | INTEGER | Écart de voix entre l'élu et le 2ème (NULL si candidat unique) |
| `marge_victoire_pct` | REAL | % d'écart sur les suffrages exprimés (NULL si candidat unique) |

**Usage :** Questions sur une circonscription spécifique, "qui a gagné à X", résumé d'une zone.

### 10. `vw_close_races` — Élections les plus serrées (pré-triées)

**But :** Répondre aux questions "les résultats les plus serrés", "élection la plus disputée", "victoire la plus écrasante", "quelle circonscription a eu l'écart le plus faible".

> Triée par `marge_victoire_pct ASC` (la plus serrée en premier). Seules les circonscriptions avec au moins 2 candidats apparaissent.

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Région |
| `numero_circonscription` | INTEGER | Numéro de la circonscription |
| `circonscription` | TEXT | Nom de la circonscription |
| `elu_candidat` | TEXT | Nom du candidat élu |
| `elu_parti` | TEXT | Parti de l'élu |
| `elu_scores` | INTEGER | Score de l'élu |
| `elu_score_pct` | REAL | % de l'élu |
| `runner_up_scores` | INTEGER | Score du 2ème candidat |
| `marge_victoire` | INTEGER | Écart de voix (elu - 2ème) |
| `marge_victoire_pct` | REAL | % d'écart sur les suffrages exprimés |
| `nb_candidats` | INTEGER | Nombre de candidats en lice |
| `inscrits` | INTEGER | Électeurs inscrits |
| `votants` | INTEGER | Votants |
| `taux_participation` | REAL | Taux de participation (%) |
| `taux_abstention` | REAL | Taux d'abstention (%) |

**Exemples :**
```sql
-- Top 10 élections les plus serrées
SELECT circonscription, elu_candidat, elu_parti, marge_victoire, marge_victoire_pct
FROM vw_close_races
LIMIT 10;

-- Élection la plus serrée
SELECT *
FROM vw_close_races
LIMIT 1;

-- Victoires les plus écrasantes (inverser le tri)
SELECT circonscription, elu_candidat, marge_victoire_pct
FROM vw_close_races
ORDER BY marge_victoire_pct DESC
LIMIT 10;
```

### 8. `vw_party_scores_by_region` — Scores agrégés par (région, parti) avec classement

**But :** Répondre aux questions "quel parti a gagné à Abidjan", "quel parti a eu le Nème meilleur score dans la région X", "classement des partis par région", "quel parti a dominé la région X".

> **IMPORTANT :** Pour toute question sur les scores/performances/sièges **d'un parti dans une région**, utiliser CETTE vue et non `results` ni `vw_results_by_party`.
>
> MAUVAIS : `SELECT parti FROM vw_results_by_party WHERE region ILIKE '%ABIDJAN%'` → erreur, pas de colonne `region`
> BON : `SELECT parti, nb_sieges FROM vw_party_scores_by_region WHERE region ILIKE '%ABIDJAN%' ORDER BY nb_sieges DESC`

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Région administrative |
| `parti` | TEXT | Parti politique |
| `nb_candidats` | INTEGER | Nombre de candidats du parti dans la région |
| `nb_circonscriptions` | INTEGER | Nombre de circonscriptions où le parti était présent |
| `total_scores` | INTEGER | Total des voix obtenues par le parti dans la région |
| `pct_scores_region` | REAL | % des voix totales de la région obtenues par ce parti |
| `nb_sieges` | INTEGER | Sièges remportés dans la région |
| `total_inscrits` | INTEGER | Total inscrits dans les circonscriptions du parti |
| `total_votants` | INTEGER | Total votants dans ces circonscriptions |
| `taux_participation` | REAL | Taux de participation pondéré (%) |
| `taux_abstention` | REAL | Taux d'abstention pondéré (100 - taux_participation) |
| `total_suffrages_exprimes` | INTEGER | Total suffrages exprimés |
| `classement_region` | INTEGER | Rang du parti dans la région (1 = 1er score, 2 = 2ème, …) |

⚠️ Cette vue n'a PAS de colonne `circonscription` — elle agrège par `region` uniquement. Pour filtrer par ville/circonscription, utiliser `vw_candidates_ranked_by_circonscription` ou `results` directement.

**Exemples :**
```sql
-- 2ème meilleur parti dans AGNEBY-TIASSA
SELECT parti, total_scores, classement_region
FROM vw_party_scores_by_region
WHERE region ILIKE '%AGNEBY-TIASSA%' AND classement_region = 2
LIMIT 5;

-- Classement complet des partis dans une région
SELECT classement_region, parti, total_scores, pct_scores_region, nb_sieges
FROM vw_party_scores_by_region
WHERE region ILIKE '%ABIDJAN%'
ORDER BY classement_region
LIMIT 20;

-- Dans combien de régions le RHDP était-il 1er ?
SELECT COUNT(*) AS nb_regions_premier
FROM vw_party_scores_by_region
WHERE parti = 'RHDP' AND classement_region = 1;

-- Participation par parti dans chaque région
SELECT region, parti, taux_participation, total_votants, total_inscrits
FROM vw_party_scores_by_region
WHERE parti = 'RHDP'
ORDER BY taux_participation DESC
LIMIT 50;
```

### 9. `vw_candidates_ranked_by_circonscription` — Classement des candidats par circonscription

**But :** Répondre aux questions "qui était 2ème dans la circonscription X", "écart entre 1er et 2ème", "candidats les mieux placés", classements individuels.

> **IMPORTANT :** Pour "le Nème candidat" dans une circonscription, utiliser CETTE vue. La colonne `classement_circonscription` est pré-calculée — pas besoin de OFFSET fragile.

| Colonne | Type | Description |
|---------|------|-------------|
| `region` | TEXT | Région |
| `numero_circonscription` | INTEGER | Numéro de la circonscription |
| `circonscription` | TEXT | Nom de la circonscription |
| `parti` | TEXT | Parti du candidat |
| `candidat` | TEXT | Nom du candidat |
| `scores` | INTEGER | Voix obtenues |
| `score_pct` | REAL | % des suffrages |
| `elu` | BOOLEAN | TRUE si élu |
| `classement_circonscription` | INTEGER | Rang dans la circonscription (1 = 1er, 2 = 2ème, …) |

**Exemples :**
```sql
-- 2ème candidat par scores dans la circonscription 5
SELECT candidat, parti, scores, classement_circonscription
FROM vw_candidates_ranked_by_circonscription
WHERE numero_circonscription = 5 AND classement_circonscription = 2
LIMIT 1;

-- Top 3 candidats par scores dans toutes les circonscriptions d'une région
SELECT region, circonscription, classement_circonscription, candidat, parti, scores
FROM vw_candidates_ranked_by_circonscription
WHERE region ILIKE '%AGNEBY-TIASSA%' AND classement_circonscription <= 3
ORDER BY numero_circonscription, classement_circonscription
LIMIT 50;
```

---

## Règles SQL

1. **SELECT uniquement** — Pas de INSERT, UPDATE, DELETE, DROP, ALTER, CREATE
2. **LIMIT obligatoire** — Maximum 1000, défaut 100
3. **Colonnes existantes uniquement** — Utiliser SEULEMENT les colonnes listées ci-dessus
4. **Tables existantes uniquement** — Utiliser SEULEMENT : results, summary_national, vw_winners, vw_turnout, vw_results_by_region, vw_results_by_party, vw_results_by_circonscription, vw_party_scores_by_region, vw_candidates_ranked_by_circonscription, vw_close_races
5. **Pas de sous-requêtes > 2 niveaux**
6. **Comparaisons texte** — Utiliser `ILIKE` pour les recherches textuelles (insensible à la casse)
7. **Agrégations** — Préférer les vues précalculées quand possible plutôt que d'agréger `results` directement

---

## Exemples de requêtes valides

```sql
-- Combien de sièges a gagné le RHDP au niveau national ?
SELECT nb_sieges FROM vw_results_by_party WHERE parti = 'RHDP';

-- Quel parti a gagné à Abidjan ? (région → utiliser vw_party_scores_by_region)
SELECT parti, nb_sieges, total_scores, pct_scores_region
FROM vw_party_scores_by_region
WHERE region ILIKE '%ABIDJAN%' AND nb_sieges > 0
ORDER BY nb_sieges DESC
LIMIT 10;

-- Classement des partis dans la région PORO
SELECT classement_region, parti, total_scores, nb_sieges
FROM vw_party_scores_by_region
WHERE region ILIKE '%PORO%'
ORDER BY classement_region
LIMIT 20;

-- 2ème meilleur parti dans la région AGNEBY-TIASSA
SELECT parti, total_scores, pct_scores_region, nb_sieges, classement_region
FROM vw_party_scores_by_region
WHERE region ILIKE '%AGNEBY-TIASSA%' AND classement_region = 2
LIMIT 5;

-- Top 10 candidats individuels par score dans une région
SELECT candidat, parti, scores, score_pct
FROM results
WHERE region ILIKE '%AGNEBY%'
ORDER BY scores DESC
LIMIT 10;

-- Taux de participation par région
SELECT region, taux_participation, taux_abstention
FROM vw_results_by_region
ORDER BY taux_participation DESC
LIMIT 100;

-- Région avec le plus fort taux d'abstention
SELECT region, taux_abstention, taux_participation
FROM vw_results_by_region
ORDER BY taux_abstention DESC
LIMIT 1;

-- Circonscriptions avec le plus fort taux d'abstention
SELECT region, circonscription, taux_abstention, taux_participation
FROM vw_turnout
ORDER BY taux_abstention DESC
LIMIT 10;

-- Histogramme des élus par parti (national)
SELECT parti, nb_sieges
FROM vw_results_by_party
WHERE nb_sieges > 0
ORDER BY nb_sieges DESC;

-- Qui a gagné dans la circonscription 001 ?
SELECT candidat, parti, scores, score_pct
FROM vw_winners
WHERE numero_circonscription = 1;

-- Taux de participation national
SELECT taux_participation FROM summary_national;

-- Nombre total de candidats indépendants
SELECT nb_candidats FROM vw_results_by_party WHERE parti = 'INDEPENDANT';

-- Top 5 élections les plus serrées
SELECT circonscription, elu_candidat, elu_parti, marge_victoire, marge_victoire_pct
FROM vw_close_races
LIMIT 5;

-- Marge de victoire dans une circonscription spécifique
SELECT circonscription, elu_candidat, runner_up_scores, marge_victoire, marge_victoire_pct
FROM vw_results_by_circonscription
WHERE numero_circonscription = 5;
```

---

## Partis politiques connus dans le dataset

- RHDP (Rassemblement des Houphouëtistes pour la Démocratie et la Paix)
- PDCI-RDA (Parti Démocratique de Côte d'Ivoire)
- FPI (Front Populaire Ivoirien)
- INDEPENDANT (candidats sans parti)
- ADCI
- MGC
- (autres à compléter après extraction complète)

## Régions connues (à compléter après extraction)

- AGNEBY-TIASSA
- ABIDJAN
- (à compléter avec la liste exhaustive après ingestion)
