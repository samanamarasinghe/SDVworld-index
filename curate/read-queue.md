# Full-text read queue

Records whose abstract suggests meaningful SDV use but does not establish it.
Reading one means fetching the paper, then patching with `"override": true`,
`confidence: "high"` and a `source_url` naming what was read.

Everything else in batches 001, 003 and 004 sits at `confidence: "medium"` on
abstract evidence, which is accurate labelling rather than a gap.

## Priority: the paper is about SDV or its models

| id | why |
|---|---|
| `W3031844875` | Database constraints in synthetic generation — directly adjacent to SDV's constraint work. Whether it extends SDV or replaces it changes how it should be filed. |
| `W4411027693` | "Challenges and Limitations of TVAE Tabular Synthetic Data Generator" — wholly about a core SDV model, and no abstract is indexed. |
| `W7163879309` | rsdv, the R reimplementation. Classified `derivative_work`; confirm from the package source whether it ports SDV or arrives at the design independently. |

## No abstract indexed, SDV signal in the title

| id | title fragment |
|---|---|
| `W7154494127` | Evaluating fidelity in synthetic tabular data generation: CTGAN vs TVAE |
| `W4390129643` | Fs-TGAN, IoT intrusion detection |
| `W4404517135` | Gaussian copulas and GANs for generation |
| `W4413164562` | TGAN vs other GAN models, synthetic earthquake data |
| `W4413350499` | DGA fault diagnosis, Gaussian copula augmentation |
| `W4404321591` | Ultimate axial strength prediction |
| `W7130506921` | Exploratory data analysis through synthetic data generation |
| `W7160423075` | Synthetic foamed concrete mixtures |
| `W7165478275` | CART and Gaussian Copula, comparative |

## Signal present but role unclear

| id | why |
|---|---|
| `W4383899825` | Rust damage diagnosis for street light poles. CTGAN appears in the record but the abstract describes only the sensor network. |

## Also worth resolving

Duplicate OpenAlex records to merge at promotion time:
`W4387517159` / `W4387521899` (C3-TGAN),
`W4390601317` / `W4393319426` (OpenWiFi anonymization),
`W4415483341` / `W7131660599` (child and adolescent mental health).

And two `source_work` records — `W2902901670` (TGAN) and `W2954395498` (CTGAN) —
which are the anchor papers themselves, already in `data/shards/01-first-party.json`
and to be excluded from tail promotion.
