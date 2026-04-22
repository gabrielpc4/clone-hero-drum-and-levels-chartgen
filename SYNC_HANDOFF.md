# Handoff — Sincronização temporal de MIDI externo → PART DRUMS no chart CH

> Este documento descreve **um problema específico** que ainda não resolvemos.
> Não lista tentativas anteriores — queremos que você aborde com olhar fresco.

## 1. Contexto do projeto

Projeto: gerador automático de charts de bateria para **Clone Hero** a partir
de transcrições MIDI públicas (Songsterr, Guitar Pro, MuseScore).

### Cenário real (produção)

A custom song tem apenas:
- `notes.mid` ou `notes.chart` com **PART GUITAR Expert** (feita pelo charter,
  sincronizada com o áudio real `song.opus`/`song.ogg` que acompanha a custom).
- Metadados (`song.ini`), capa, stems de áudio.
- **Não tem PART DRUMS.** Justamente o que queremos gerar.

O usuário baixa um MIDI externo da música (ex: Songsterr) que contém drums +
guitars + bass etc, e quer converter a drum dele numa **PART DRUMS Expert
alinhada com o áudio do chart CH**.

### Cenário de validação (onde estamos testando)

Para validar, estamos usando charts da **Harmonix** (Rock Band originais) — elas
têm PART DRUMS Expert oficial. Se a gente consegue gerar algo próximo do oficial
a partir do MIDI Songsterr, o algoritmo funciona.

Casos de teste atuais:
- `System of a Down - Chop Suey (Harmonix)` + Songsterr MIDI
- `System of a Down - Toxicity (Harmonix)` + Songsterr MIDI

## 2. O problema

**Drift temporal**: quando convertemos a bateria do MIDI externo para ticks do
chart CH, as notas drum ficam ligeiramente adiantadas ou atrasadas em relação
ao áudio real. A primeira nota normalmente fica alinhada, mas vai derrapando ao
longo da música.

Causa fundamental:

- O **áudio real** tem um tempo musical específico (BPM + microvariações
  naturais do baterista humano).
- O **chart CH** (PART GUITAR) foi feito em cima do áudio — seu `tempo map`
  MIDI reflete bem o áudio (tempos e microvariações).
- O **MIDI externo** (Songsterr) tem **tempo map inventado pelo transcritor**.
  Às vezes é BPM constante mesmo onde o áudio varia; às vezes usa
  `time_signature` completamente diferente (ex: Songsterr escreve Toxicity em
  6/8, Harmonix escreve em 4/4).

Exemplos concretos das duas músicas de teste:

| Música | Fonte | TPB | BPM | Time sig |
|---|---|---|---|---|
| Chop Suey | Songsterr | 15360 | 130 const | 3/4 → 4/4 |
| Chop Suey | Harmonix | 480 | 127 variável (125–129) | 4/4 |
| Toxicity | Songsterr | 15360 | 114 const (→121 em alguns trechos) | 6/8 |
| Toxicity | Harmonix | 480 | 77 variável (~76–80) | 4/4 |

- Em **Chop Suey**, BPMs estão próximos (130 vs 127) — drift é muito pequeno.
- Em **Toxicity**, BPMs nominais divergem MUITO (114 vs 77) por conta do time
  sig diferente. A música real dura **~224 segundos em ambas as fontes**
  (Songsterr 218s, Harmonix 224s — diferença pode ser por corte final).

Ou seja: cada fonte descreve a mesma música, mas com NOTAÇÃO rítmica diferente,
e o tempo map de uma não é confiável como referência absoluta do áudio.

## 3. Dados disponíveis

Para resolver o sync você pode usar:

### Do chart CH (ref_mid)

- `PART GUITAR` — notas Expert (pitches 96–100) sincronizadas com áudio.
  **Fonte confiável** de onde a música começa/termina e de onde cada ataque
  musical cai no tempo real.
- `tempo map` (track 0) — reflete o tempo real do áudio (variações de BPM).
- `time_signature` events — indicam compassos do chart.
- Track `EVENTS` — geralmente tem `[section X]`, `[music_start]`,
  `[crowd_X]` nas Harmonix. Customs **não** têm isso garantido; não dependa.
- `PART DRUMS` **só existe no caso de validação** (Harmonix). Em produção não vai existir.

### Do MIDI externo (src_mid)

- **Track de bateria** (canal 9, GM) — o que queremos converter.
- Várias **tracks de guitarra/baixo** com nomes variados (ex: "Daron Malakian
  | Ibanez Iceman | Rhythm Guitar 1"). Podem conter a mesma música que o
  chart CH charteou, mas também podem conter conteúdo EXTRA (ex: intro
  acústica que o Harmonix não charteou).
- `tempo map` (track 0) — nem sempre reflete o áudio real fielmente.
- `time_signature` events.

### Peculiaridades conhecidas das transcrições Songsterr

- Quantização pode divergir da música real. Ex: Toxicity tem tercinas no riff
  principal (Harmonix quantizou assim); Songsterr transcreveu em colcheias.
- Contagem de baqueta (side stick GM 37) no início da drum antes da música
  começar.
- Acordes são transcritos nota-a-nota (uma note_on por corda) — precisa de
  collapsing para virar um "gem event".

## 4. Ferramentas já implementadas

Diretório do projeto: `/Users/gabrielcarvalho/Downloads/system/`

### Parsers

- `_analysis/parse_chart.py` — lê `PART GUITAR` do formato RB/Harmonix MIDI.
- `_analysis/parse_drums.py` — lê `PART DRUMS` (usado só pra validar contra
  oficial no cenário de teste).

### Importador atual

- `_analysis/import_songsterr.py` — pipeline funcional mas com sync simples.
  Já resolve bem as partes não-temporais:
  - Mapa GM→RB drums (kick, snare, toms, pratos).
  - Tom mapping dinâmico (pitches GM → Y/B/G pelo ranking dos pitches usados
    naquela música — evita colapsar dois toms distintos em uma só lane).
  - Open hi-hat classification (GM 46 vira Y se é dominante na música,
    senão B = ride/accent).
  - Dedup de flams (pares mesma-lane com gap ≤ 1/16 beat): snare vira R+Y
    simultâneo; outras lanes perdem a 2ª nota.
  - Drop de contagem de baqueta.
  - Preserva tom markers (110/111/112) para Pro Drums.

Uso:

```bash
python3 _analysis/import_songsterr.py <externo.mid> <chart_ref.mid> <saida.mid> \
  [--offset-beats N] [--drop-before-src-beat N] [--dedup-beats N]
```

**O que o importador NÃO está resolvendo bem: a sincronização temporal
contínua ao longo da música.** Funciona razoavelmente para músicas com BPM
próximo e estável entre src e ref (Chop Suey), mas diverge em casos mais
complexos (Toxicity).

## 5. Validação

### Pipeline de teste

Para validar contra ground truth (Harmonix):

```bash
python3 _analysis/import_songsterr.py \
  "System of a Down - Toxicity (Harmonix)/System of a Down-Toxicity-04-20-2026.mid" \
  "System of a Down - Toxicity (Harmonix)/notes.mid" \
  "System of a Down - Toxicity (Harmonix)/notes.songsterr.mid" \
  --offset-beats 0 --drop-before-src-beat 24
```

Comparar gerado vs oficial Harmonix:

```python
import mido
from _analysis.parse_drums import parse_drums
from bisect import bisect_left
a = parse_drums(mido.MidiFile(".../notes.mid"))["Expert"]            # oficial
b = parse_drums(mido.MidiFile(".../notes.songsterr.mid"))["Expert"]   # gerado
at = sorted({n.tick for n in a.notes}); bt = sorted({n.tick for n in b.notes})
for tol in (30, 60, 120):  # tpb=480
    m = sum(1 for t in at if (i:=bisect_left(bt, t-tol)) < len(bt) and bt[i] <= t+tol)
    print(f"±{tol} ticks: {m/len(at):.0%}")
```

Métrica útil: **match ±30 ticks** (= ±1/16 beat @ TPB 480). Se >= 90%,
sincronização boa. 50–70% = drift visível audível. < 50% = desalinhado.

### Validação auditiva

O usuário abre o `notes.songsterr.mid` no Moonscraper (editor) junto com o
áudio e ouve/compara com o `notes.mid` original. O gerado vive em
`System of a Down - X (Harmonix)/notes.songsterr.mid`.

Há um script `sync_to_whisky.sh` que sincroniza os arquivos para o Desktop
do Whisky (wrapper Wine do Mac), onde o Moonscraper roda.

## 6. Overrides que o usuário pode fornecer

O usuário está no loop de validação. Se o sync automático falha, aceita usar
flags manuais. Abordagens que dependam do usuário fornecer informação são OK
(ex: "qual compasso o verse começa no áudio?"), desde que a quantidade de
input manual seja razoável.

Em customs reais, o charter geralmente deixa markers no `.chart` CH para
seções da música ("[section verse_1]" etc) — mas isso não é garantido.

## 7. O desafio em uma frase

**Mapear tempos do MIDI externo (cujo tempo map pode ser inexato em relação
ao áudio) para tempos do chart CH (cujo tempo map é a verdade em relação ao
áudio), de forma que as notas de bateria do externo caiam no tempo correto
do áudio ao longo de toda a música — usando a PART GUITAR do chart CH como
sinal confiável.**

Boa sorte!
