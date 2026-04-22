# Handoff — Engenharia reversa das reduções de dificuldade do Clone Hero (Harmonix → CH)

> **Contrato deste documento:** este é o estado-da-arte do projeto. Qualquer LLM que abrir este arquivo deve conseguir continuar exatamente de onde paramos, sem precisar de mais contexto além do que está aqui. **Atualize-o a cada descoberta, particularidade ou decisão.** Se algo for refutado depois, marque como ~~tachado~~ e adicione a correção logo abaixo, com data.
>
> Idioma: Português (preferência do usuário). Comentários internos do código podem ficar em inglês.

---

## 1. Objetivo do projeto

O usuário tem charts oficiais da Harmonix (origem Rock Band) das músicas do System of a Down convertidas para Clone Hero. Cada música tem **Easy / Medium / Hard / Expert** já feitos para guitarra, baixo, bateria e vocal.

A meta final é **ensinar uma LLM a, dada apenas a chart Expert (de guitarra ou bateria), gerar Easy / Medium / Hard com qualidade equivalente à oficial da Harmonix.** Em paralelo, **gerar charts de bateria a partir de MIDIs do Guitar Pro** (track de bateria multi-track exportada para MIDI) — esta é a frente futura.

Foco atual: **GUITARRA concluída (gerador v4 funcional)**. **BATERIA em estudo** — análise estrutural concluída (ver §13), construção do reducer de drums pendente.

Estratégia:
1. **Etapa 1 — Validação estrutural** ✅ (concluída): confirmar como o `notes.mid` representa cada faixa/dificuldade.
2. **Etapa 2 — Pesquisa de padrões**: alinhar Expert↔Hard↔Medium↔Easy tick a tick em todas as 6 músicas-base e catalogar **o que foi mantido, removido, simplificado e transposto** em cada redução.
3. **Etapa 3 — Síntese das regras**: derivar uma lista de regras determinísticas + heurísticas que reproduzam as reduções oficiais a partir do Expert.
4. **Etapa 4 — Validação**: aplicar as regras a cada Expert, comparar com Hard/Medium/Easy oficiais, medir similaridade, iterar até atingir paridade.
5. **Etapa 5 — Generalização**: aplicar às músicas que o usuário trouxer fora desse conjunto inicial.

Recursos que o usuário pode fornecer sob demanda: tabs Guitar Pro multi-track. Pesquisa web é permitida.

---

## 2. Estrutura do diretório de trabalho

Raiz: `/Users/gabrielcarvalho/Downloads/system/`

```
System of a Down - Aerials (Harmonix)/
System of a Down - B.Y.O.B. (Harmonix)/
System of a Down - Chop Suey (Harmonix)/
System of a Down - Hypnotize (Harmonix)/
System of a Down - Spiders (Harmonix)/
System of a Down - Toxicity (Harmonix)/
_analysis/
  parse_chart.py            # parser canônico (Harmonix MIDI → Chart)
  align.py                  # alinhamento Expert↔reduções, métricas globais
  deep_dive.py              # órfãs, transposições, bursts, anchor
  finer.py                  # HOPO/Tap, anchor de seção, drop-vs-single, sustain mode
  alignment_report.json     # output do align.py (dataset Q1–Q4)
  reducer.py                # gerador v4: reduce_chart(expert, "Easy|Medium|Hard")
  midi_writer.py            # writer notes.gen.mid + diff vs original
  validate.py               # F1/precision/recall por música/dificuldade
HANDOFF.md                  # este arquivo

# Saída do gerador (em cada pasta de música):
"System of a Down - <X> (Harmonix)/notes.gen.mid"
```

Cada pasta de música contém:
- `notes.mid` — chart (objeto principal de estudo)
- `song.ini` — metadados (BPM, dificuldades, charter etc.)
- `album.jpg`
- Stems de áudio: `song.opus`, `guitar.opus`, `rhythm.opus`, `drums_1.opus`…`drums_3.opus`, `vocals.opus`, `crowd.opus`

> **Importante:** o repositório **não é git**. Não rode `git status`/`git log` esperando histórico.

---

## 3. Formato Harmonix MIDI — referência confirmada nas 6 músicas

- **Tipo:** MIDI Type 1
- **Resolução:** 480 ticks por beat (TPB) em todas as 6 músicas
- **Faixa 0:** conductor — contém tempo (`set_tempo`) e fórmula de compasso (`time_signature`)
- **Faixas nomeadas:** `PART GUITAR`, `PART BASS`, `PART DRUMS`, `PART VOCALS`, `EVENTS`, `VENUE`, `BEAT`

Dentro de cada `PART <instrumento>`, **as 4 dificuldades coexistem** como blocos separados de pitch MIDI:

| Dificuldade | Open strum | G | R | Y | B | O | Force-HOPO ON / OFF |
|---|---|---|---|---|---|---|---|
| Easy   | 58 | 60 | 61 | 62 | 63 | 64  | 65 / 66 |
| Medium | 70 | 72 | 73 | 74 | 75 | 76  | 77 / 78 |
| Hard   | 82 | 84 | 85 | 86 | 87 | 88  | 89 / 90 |
| Expert | 94 | 96 | 97 | 98 | 99 | 100 | 101 / 102 |

**Marcadores compartilhados pela faixa inteira (não dependem de dificuldade):**

| Pitch | Significado |
|---|---|
| 103 | Star Power (RB2+ / RBN). Nas 6 músicas atuais a Harmonix usa o esquema RB1: 105/106. |
| 104 | Tap section (extensão do Clone Hero) |
| 105 / 106 | Player 1 / Player 2 marker — usado pela Harmonix nesses charts. Em Chop Suey, durações de 3600 ticks indicam que demarcam seções, **não** notas individuais. |
| 108 | Frase de letra (em PART VOCALS) |
| 116 | **Overdrive / Star Power** — fonte da verdade da SP nessas charts |
| 120–124 | Drum fill / Big Rock Ending (em PART DRUMS) |
| 40–59 | Animação de mão / posição de fret no braço (ignorar para chart logic) |

**Observação prática:** ao contar notas de uma dificuldade só conte pitches dentro de `[base, base+4]` (mais o open em `base-2`). O resto (40-59, 105/106, 116, 120-124) é metadado e não conta como gem.

### 3.1 Verificação amostral

Em **Chop Suey**, no tick **3840** (primeiro hit do riff), disparam simultaneamente:

```
pitch 61  → Easy R
pitch 74  → Medium Y
pitch 85, 86 → Hard R+Y
pitch 97, 98 → Expert R+Y
```

Isso confirma que: (a) as 4 dificuldades ficam alinhadas no mesmo tick para o mesmo "hit musical", (b) acordes Expert podem ser reduzidos a uma única nota em níveis menores.

---

## 4. Parser canônico

Arquivo: `_analysis/parse_chart.py`

Dependência: `mido` (já instalada via `pip3 install mido --break-system-packages`).

API principal:

```python
from parse_chart import parse_part, chart_summary
import mido
mid = mido.MidiFile("/.../notes.mid")
charts = parse_part(mid, "PART GUITAR")  # {"Easy": Chart, "Medium": Chart, "Hard": Chart, "Expert": Chart}
print(chart_summary(charts["Expert"]))
```

Estruturas de dados:

```python
@dataclass
class Note:
    tick: int           # tick absoluto de início
    end_tick: int       # tick absoluto de fim
    frets: tuple[int]   # ex: (0,) = G; (0,2) = G+Y; () = open strum
    is_open: bool
    forced_hopo: int    # +1 = HOPO on, -1 = HOPO off, 0 = sem forçar
    is_tap: bool

@dataclass
class Chart:
    instrument: str
    difficulty: str
    ticks_per_beat: int
    notes: list[Note]
    overdrive: list[(start, end)]
    solos: list[(start, end)]
    tempos: list[(tick, microseconds_per_beat)]
    time_sigs: list[(tick, num, denom)]
```

> **Decisão de design:** notas simultâneas no mesmo tick são agrupadas em um único `Note` (acorde). É assim que o jogo as enxerga.

---

## 5. Estatísticas brutas das 6 músicas (PART GUITAR)

Geradas pelo parser. Coluna `chord_size` = histograma de tamanho de acorde (1=nota única, 2=acorde duplo etc.).

```
Aerials
  Easy   notes= 204 chords=  0 sus= 204 frets={G:74, R:67, Y:59, B:1,  O:2}    sizes={1:203, open:1}
  Medium notes= 309 chords=107 sus= 309 frets={G:94, R:157,Y:91, B:73, O:1}    sizes={1:202, 2:107}
  Hard   notes= 558 chords=179 sus= 558 frets={G:117,R:211,Y:85, B:99, O:225}  sizes={1:379, 2:179}
  Expert notes= 937 chords=305 sus= 929 frets={G:223,R:349,Y:84, B:300,O:292}  sizes={1:632, 2:299, 3:6}

B.Y.O.B.
  Easy   notes= 269 chords=  0 sus= 253 frets={G:130,R:95, Y:44}                sizes={1:269}
  Medium notes= 485 chords=170 sus= 423 frets={G:97, R:213,Y:272,B:73}          sizes={1:315, 2:170}
  Hard   notes= 812 chords=322 sus= 574 frets={G:118,R:338,Y:284,B:286,O:108}   sizes={1:490, 2:322}
  Expert notes=1590 chords=439 sus=1103 frets={G:518,R:693,Y:343,B:366,O:109}   sizes={1:1151,2:439}

Chop Suey
  Easy   notes= 273 chords=116 sus= 273 frets={G:115,R:149,Y:125}               sizes={1:157, 2:116}
  Medium notes= 471 chords=191 sus= 471 frets={G:147,R:184,Y:188,B:143}         sizes={1:280, 2:191}
  Hard   notes= 800 chords=365 sus= 800 frets={G:177,R:218,Y:308,B:258,O:204}   sizes={1:435, 2:365}
  Expert notes=1052 chords=589 sus=1052 frets={G:246,R:299,Y:446,B:345,O:305}   sizes={1:463, 2:589}

Hypnotize
  Easy   notes= 120 chords=  0 sus= 120 frets={G:62, R:28, Y:24, B:2,  O:1}     sizes={1:117, open:3}
  Medium notes= 234 chords=106 sus= 230 frets={G:94, R:125,Y:86, B:34, O:1}     sizes={1:128, 2:106}
  Hard   notes= 410 chords=164 sus= 404 frets={G:113,R:98, Y:197,B:90, O:76}    sizes={1:246, 2:164}
  Expert notes= 756 chords=260 sus= 692 frets={G:341,R:153,Y:223,B:176,O:123}   sizes={1:496, 2:260}

Spiders
  Easy   notes= 191 chords=  0 sus=  1  frets={G:68, R:63, Y:56, B:2,  O:2}     sizes={1:191}
  Medium notes= 317 chords=263 sus=  3  frets={G:102,R:171,Y:181,B:123,O:3}     sizes={1:54,  2:263}
  Hard   notes= 543 chords=393 sus= 15  frets={G:223,R:217,Y:208,B:245,O:43}    sizes={1:150, 2:393}
  Expert notes= 653 chords=471 sus= 163 frets={G:223,R:152,Y:405,B:320,O:181}   sizes={1:182, 2:314, 3:157}

Toxicity
  Easy   notes= 251 chords=  0 sus=  0  frets={G:86, R:96, Y:69}                sizes={1:251}
  Medium notes= 372 chords= 85 sus=  0  frets={G:143,R:135,Y:136,B:43}          sizes={1:287, 2:85}
  Hard   notes= 610 chords=157 sus=  0  frets={G:160,R:180,Y:188,B:158,O:81}    sizes={1:453, 2:157}
  Expert notes= 985 chords=234 sus= 22  frets={G:306,R:287,Y:289,B:223,O:114}   sizes={1:751, 2:234}
```

---

## 6. Padrões já comprovados (regras candidatas — *fortes*)

Estas regras são consistentes nas **6 músicas** observadas. Marcadas como candidatas até a Etapa 4 confirmar.

### 6.1 Composição de acordes (limites duros)

| Dificuldade | Tamanho máximo de acorde observado | Frequência |
|---|---|---|
| Easy   | **1** (nota única SEMPRE) | 0 acordes em 6/6 músicas |
| Medium | **2** | acordes 2-notas comuns; 3+ NUNCA |
| Hard   | **2** | acordes 2-notas comuns; 3+ NUNCA |
| Expert | **3** (raramente 4) | acordes 3-notas em Aerials (6) e Spiders (157) |

**→ Regra R1:** Easy = sem acordes. Qualquer acorde do Expert vira nota única. **R2:** Medium/Hard = acordes ≤ 2 notas. Qualquer 3-acorde do Expert vira ≤ 2 notas.

### 6.2 Trastes acessíveis

| Dificuldade | Trastes "esperados" | Exceções |
|---|---|---|
| Easy   | **G, R, Y** (3 primeiros) | B/O aparecem só como sustain isolado e raríssimo (≤3 notas em Aerials/Hypnotize) |
| Medium | G, R, Y, B (4 primeiros) | Orange (O) aparece em ~1 nota isolada em Aerials/Medium |
| Hard   | Todos (G,R,Y,B,O) | — |
| Expert | Todos | — |

**→ Regra R3:** Easy quase nunca usa B/O. **R4:** Medium quase nunca usa O.

### 6.3 Densidade total

Razões observadas (notas dividido por Expert):

| Música     | Easy/X | Medium/X | Hard/X |
|---|---|---|---|
| Aerials    | 0.218 | 0.330 | 0.595 |
| B.Y.O.B.   | 0.169 | 0.305 | 0.511 |
| Chop Suey  | 0.260 | 0.448 | 0.760 |
| Hypnotize  | 0.159 | 0.310 | 0.542 |
| Spiders    | 0.292 | 0.485 | 0.831 |
| Toxicity   | 0.255 | 0.378 | 0.619 |
| **Média**  | **0.226** | **0.376** | **0.643** |

**→ Hipótese H1:** alvos de densidade aproximados para gerar Easy ≈ 22-26%, Medium ≈ 35-45%, Hard ≈ 60-75% do Expert. A variação por música indica que **a densidade não é uma simples taxa fixa** — depende também da estrutura da música (quanto mais repetitivo o riff, mais Hard se aproxima do Expert).

### 6.4 Sustains

Diferença drástica entre músicas:
- **Aerials/Chop Suey/B.Y.O.B./Hypnotize:** Easy preserva quase 100% dos sustains do número total de notas (porque Easy fica só com as notas longas).
- **Spiders:** quase nenhum sustain em E/M/H (1, 3, 15) embora Expert tenha 163 — provavelmente porque os "sustains" curtos do Expert viram ataques nos níveis menores.
- **Toxicity:** zero sustains em E/M/H, 22 no Expert — comportamento parecido com Spiders.

**→ Hipótese H2 (refinada — ver §7.4):** sustains longos (≥ 1 beat?) são **preservados** mesmo nos níveis baixos; sustains curtos (< 1 beat) podem ser convertidos em hits sem cauda. Limiar exato precisa de validação adicional.

### 6.5 Alinhamento temporal — verificado em §7.1

---

## 7. Aprofundamento — Etapa 2 (alinhamento Expert↔reduções)

Análise rodada por `_analysis/align.py` + `_analysis/deep_dive.py`. Output completo em `_analysis/alignment_report.json`.

### 7.1 Q1 — Reduções são subconjuntos temporais do Expert?

| Música | Easy órfãs | Medium órfãs | Hard órfãs |
|---|---|---|---|
| Aerials   | 0 | 0 | 0 |
| B.Y.O.B.  | 0 | 6 | 6 |
| Chop Suey | 0 | 0 | 1 |
| Hypnotize | 0 | 0 | 0 |
| Spiders   | 0 | 0 | 0 |
| Toxicity  | 0 | 0 | 0 |

**→ R7 (forte):** ≥ 99.5% das notas em E/M/H estão em ticks que existem no Expert. As órfãs são raríssimas.
- As 6 órfãs do BYOB caem em ticks com vizinhos a ±120 ticks (16th) tendo o **mesmo fret-set** que a órfã. Provável "recuperação de uma 16th comprimida" pela Harmonix em parte rápida.
- A 1 órfã do Chop Suey (tick=168720, R) está entre `(Y,O)` e `(R,B)` separados por 240 ticks — uma nota intermediária inserida para suavizar transição entre dois acordes muito distantes.

**Implicação prática:** o gerador deve **partir do Expert** e tomar decisões de "manter / dropar / transpor" tick a tick. Inserir notas novas é **exceção rara** (≤ 0.5% dos casos), só justificável para suavizar gaps grandes entre acordes muito distintos.

### 7.2 Q2 — Densidade por offset 16th do beat (sub0=on-beat, sub1=e, sub2=&, sub3=a)

Taxa de retenção (`kept / total Expert`) por sub-beat em cada música:

```
                           Easy                Medium               Hard
sub  Aerials    sub0 56%  sub1  0% sub2 18% sub3  7% | 73%/16%/18%/20% | 86%/34%/74%/37%
     B.Y.O.B.   sub0 50%  sub1  0% sub2  9% sub3  0% | 69%/ 2%/24%/14% | 76%/ 2%/79%/16%
     Chop Suey  sub0 73%  sub1  0% sub2  3% sub3  0% | 98%/ 2%/40%/ 4% | 99%/55%/92%/36%
     Hypnotize  sub0 49%  sub1  0% sub2  0% sub3  0% | 94%/ 0%/ 4%/ 0% | 94%/ 5%/93%/ 2%
     Spiders    sub0 49%  sub1  0% sub2 13% sub3  0% | 79%/ 0%/23%/ 0% | 99%/ 0%/87%/ 0%
     Toxicity   sub0 72%  sub1  3% sub2  2% sub3  0% | 74%/ 9%/33%/ 0% | 81%/59%/67%/ 0%
```

**→ R5 (forte):** prioridade absoluta de retenção é `sub0 (on-beat) ≫ sub2 (& do beat) ≫ sub1, sub3 (16ths fracos)`.
- **Easy** = essencialmente "**on-beat only**". Drops quase 100% de sub1/sub3.
- **Medium** = "on-beat + alguns &". Drops quase 100% de sub1/sub3.
- **Hard** = "on-beat + & + alguns 16ths fracos". Sub1/sub3 só sobrevivem em músicas mais densas.
- Quando sub0 não chega a 100% mesmo no Hard (Aerials 86%, Toxicity 81%), é porque **on-beats que caem em runs muito densos também são decimados** (ver §7.5).

### 7.3 Q3 — Redução de acordes

#### 7.3.1 Distribuição (E_size, R_size) por dificuldade

```
        Easy         Medium       Hard
Aerials (2,0)214 (2,1)85 (3,1)2 (3,0)4
        (2,0)195 (2,2)104 (3,2)3 (3,0)3
        (2,0)126 (2,2)173 (3,2)6
B.Y.O.B (2,1)112 (2,0)327
        (2,1)48  (2,0)227 (2,2)164
        (2,2)316 (2,0)123
ChopSuey(2,1)89 (2,0)384 (2,2)116           ← já há (2,2) no Easy! (anomalia leve)
        (2,1)156 (2,0)242 (2,2)191
        (2,2)347 (2,0)15  (2,1)227
Hypnotize (2,0)205 (2,1)55
          (2,1)3 (2,0)151 (2,2)106
          (2,1)6 (2,2)164 (2,0)90
Spiders (3,1)56 (3,0)101 (2,1)120 (2,0)194
        (3,2)97 (3,0)60 (2,2)166 (2,0)148
        (3,2)152 (3,0)5 (2,2)241 (2,0)73
Toxicity (2,1)76 (2,0)158
         (2,2)85 (2,1)12 (2,0)137
         (2,2)156 (2,0)78
```

**Padrões consistentes:**
- **Easy:** acorde Expert vira nota única (`→1`) ou é completamente dropado (`→0`). A taxa de drop é alta — frequentemente >50% dos acordes Expert.
- **Hard:** se mantém o tick, **preserva o acorde inteiro** (`→2` é o destino dominante; intersection=2 = acorde idêntico).
- **Medium:** comportamento híbrido. Pode preservar acorde, reduzir para single, ou dropar.

#### 7.3.2 Quando vira single, qual fret sobrevive?

- **Easy:** quase sempre o **fret mais grave (lowest)** do acorde. Aerials 44/45, BYOB 104/8, Chop Suey 31/57 (lowest+transposed), Hypnotize 51/4, Spiders 103/73, Toxicity 76/0.
  - Excessões "transposed_outside" significam que o fret single da redução **não estava no acorde original** — é uma transposição (ver §7.3.3).
- **Hard:** se reduz para single, é raro mas tende a manter "highest" (Hypnotize 6 casos, Chop Suey 76 casos).

#### 7.3.3 Transposições "fora do acorde"

Padrão **CRISTALINO**: acordes Expert com spread alto são **deslocados para a esquerda (em direção a G)** preservando o **shape de intervalo**.

Mapeamentos observados (frequência total entre as 6 músicas):

| Expert chord | Easy single | Medium chord | Hard chord |
|---|---|---|---|
| `(G,Y)` | `(R,)` | `(G,R)` ×93 | identidade |
| `(R,Y)` | `(G,)` ×13 | `(G,R)` ×23 | identidade |
| `(R,B)` | `(G,Y)` ×39, `(G,R)` ×13, `(Y,)` ×6 | `(R,Y)` ×113 | identidade ou `(Y,B)` ×3 |
| `(R,O)` | `(G,Y)` ×12, `(Y,)` ×32 | `(R,B)` ×32 | identidade |
| `(Y,B)` | `(R,)` ×27, `(G,)` ×4 | `(R,Y)` ×16, `(R,B)` ×15 | identidade |
| `(Y,O)` | `(R,Y)` ×25, `(G,Y)` ×8, `(R,)` ×16, `(G,)` ×3 | `(R,B)` ×86, `(Y,B)` ×35 | identidade ou `(B,O)` |
| `(B,O)` | `(Y,)` ×31 | `(Y,B)` ×22 | identidade |
| `(G,B)` | `(R,)` ×22 | `(R,Y)` ×20, `(G,Y)` ×7 | identidade |
| `(Y,B,O)` | `(G,/R,/Y,)` | `(R,B)` ×97 (Spiders) | `(R,B)` ×103 (Spiders!) |
| `(R,Y,B)` | `(G,)` | `(G,Y)` ×23 | identidade |

**→ R8 (forte):** **regra de transposição de acorde**:
1. Calcule o **shape de intervalo** do acorde Expert (gaps entre frets, em ordem). Ex: `(R,O)` = gap 3.
2. Se o shape couber em [G..máx-fret-permitido-na-dificuldade], **comprima** para começar perto de G mantendo o shape.
3. Se o shape **não** couber:
   - Em **Medium**: comprima também o shape (gap 3 → gap 2). Ex: `(R,O)` gap 3 → `(R,B)` gap 2 (cabe em [G..B]).
   - Em **Easy**: vire single (lowest do acorde, ou um fret novo na faixa GRY).
4. Em **Hard**: praticamente nunca transpõe — preserva acorde 1:1 do Expert.

Casos **anômalos** (revisar):
- `(R,Y) → (G,R)` no Medium é literalmente "deslocar um para esquerda" — mesmo cabendo no Medium, foi deslocado. Provavelmente para alinhar com o anchor da seção (ver §7.6).
- `(G,Y) → (G,R)` no Medium ×60 (Hypnotize) — outra compressão de spread mesmo cabendo.
- `(Y,B,O) → (R,B)` no Hard — Spiders comprime esse 3-acorde fortemente, perde a O e shifteia.

**Insight extra:** a Harmonix parece ter uma **"posição de anchor da seção"** — todos os acordes da mesma seção rítmica caem na mesma região (G/R/Y se a seção é ancorada em G; R/Y/B se ancorada em R…). Investigar separadamente.

### 7.4 Q4 — Sustains: limiar e conversão

| Bucket de duração no Expert | Easy: drop / hit / sus | Medium | Hard |
|---|---|---|---|
| ≥ 1/4 nota (≥ 1 beat = TPB) | quase nunca dropado, sempre sustain | idem | idem |
| 1/8 a 1/4 (240-480 ticks) | drop ~30% (Aerials), 100% hit (Spiders/Toxicity) | drop 0% | drop 0% |
| 1/16 a 1/8 (120-240 ticks) | drop ~70-80% | drop ~50-70% | drop ~25-50% |
| < 1/16 (< 120 ticks) | drop ~85-100% | drop ~70-85% | drop ~50-70% |

**→ Refinamento de H2:**
- **Sustains ≥ 1 beat (TPB) são intocáveis** — ficam como sustain em todas as dificuldades.
- **Sustains de 1/2 a 1 beat são preservados** quase sempre, mas em músicas "agressivas" (Spiders/Toxicity) podem virar `kept_hit` — ataque sem cauda.
- **Notas curtas (< 1/8 beat = 1/16 nota)** são candidatas a drop puro; se mantidas, preservam a duração.
- Nunca observei **sustain mais longo na redução do que no Expert** (faria sentido fisicamente).

**→ R11:** A Harmonix tem dois "modos" de música:
- **Modo melódico/lento (Aerials, Chop Suey, Hypnotize, BYOB)**: preserva durações tal qual, joga fora notas curtas extras.
- **Modo agressivo (Spiders, Toxicity)**: converte tudo em hit sem sustain, mantendo só os ataques.

**Como decidir o modo?** Observação: as músicas "agressivas" têm **densidade média Expert > 1 nota/beat na maior parte das seções** ou riffs predominantemente em palm-mute/hit. Não temos métrica direta para isto ainda — investigar.

### 7.5 Q5 — Bursts (sequências de notas com gap ≤ 1/8)

Padrão observado em runs de tamanho `n`:

| Run-size n | Easy keeps ~ | Medium keeps ~ | Hard keeps ~ | Padrão de posição |
|---|---|---|---|---|
| 2 (par 16th) | 0–1 (frequentemente DELETA o par) | 1 (segunda nota) | 1–2 | quando Easy mantém 1, é a posição **1** (segunda) |
| 3 | 1 (geralmente) | 1–2 | 2–3 | Easy mantém **última**; Hard mantém todas |
| 4 | 1 | 2 | 2–3 | posições típicas: 0,3 (Easy); 1,3 (Med); 0,1,3 (Hard) |
| 5 | 1–2 | 2–3 | 3–5 | Easy: pos 4 ou 0,4; Med: 0,2,4 (1-em-2); Hard: tudo ou pula 1 |
| 7 | 2 | 2–4 | 4–6 | Med: 0,6 (extremos); Hard: 0,2,4,6 (1-em-2) |
| 9 | 2 | 4 | 5 | Easy: extremos; Med: 1-em-2; Hard: a cada ~1.5 |
| 10 | 2 | 4 | 5–6 | Med: 1,3,7,9; Hard: 1,3,5,7,9 (perfeitamente 1-em-2) |
| 18 | 4 | 7 | 11 | distribuição uniforme |
| 35 | 4–5 | 9 | 15 | distribuição uniforme com leve clustering nos extremos |
| 38 | 8 | 12 | 20 | distribuição uniforme |

**→ R9 (forte):** Em runs:
- **Decimation rate alvo**: Easy ≈ 25-40%, Medium ≈ 40-60%, Hard ≈ 50-80%.
- **Posições preferidas**: borda inicial e final tendem a ser mantidas; o miolo é decimado uniformemente.
- **Pares 16th (run=2) em Easy frequentemente são apagados juntos** — Easy não gosta de notas isoladas dentro de gaps > 1 beat.
- A "fase" da decimação (manter nota 0 ou 1 do par; manter 1,3 ou 0,3 do quartet) parece definida pelo alinhamento com o on-beat — a nota que cai mais perto do on-beat ganha prioridade.

### 7.6 Q6 — Anchor (repetição consecutiva do mesmo fret)

`mean_repeat` = quantas notas seguidas, em média, têm exatamente o mesmo fret-set.

| Música | Easy | Medium | Hard |
|---|---|---|---|
| Aerials   | 1.40 | 1.22 | 1.19 |
| B.Y.O.B.  | 1.57 | 1.75 | 1.57 |
| Chop Suey | 1.95 | 2.69 | 3.65 |
| Hypnotize | 1.52 | 1.44 | 1.89 |
| Spiders   | 2.01 | 2.44 | 1.82 |
| Toxicity  | 1.95 | 1.54 | 1.55 |

- Chop Suey Hard `mean_repeat=3.65` (`max_repeat=31`) reflete o riff de versos extremamente repetitivo no Yellow.
- **Não há tendência clara de aumentar o anchor nos níveis baixos** — pelo contrário, em algumas músicas o anchor cai (Chop Suey: 3.65→2.69→1.95). Isso porque o Easy joga fora repetições consecutivas (mantendo só uma a cada 4-8) o que diminui o run de mesmo fret.
- **Hipótese H4:** anchor não é critério primário de simplificação; é consequência do Expert + da decimação.

---

## 8. Lista consolidada de regras candidatas (para Etapa 3)

| Id | Regra | Força |
|---|---|---|
| ~~R1~~ | ~~Easy = sem acordes (todo acorde Expert vira ≤1 nota ou some)~~ → ver R17 | **refutada** |
| R2 | Medium/Hard = ≤2 notas por acorde | **Lei** |
| R17 | Easy aceita acordes ≤2 notas (GRY, spread ≤ 2) **se** a música está em "modo power-chord" (≥50% acordes pwr-spread≤2 e gap mediano ≥ 100 ticks) | Forte |
| R18 | Em Hard/Medium, dentro de um beat denso (≥3 notas), a nota com **fret mais agudo** ganha bonus de score (preserva picos de tremolo) | Heurística |
| R3 | Easy usa essencialmente {G,R,Y}; B/O só em sustain longo solitário | Forte |
| R4 | Medium usa {G,R,Y,B}; O é exceção isolada | Forte |
| R5 | Densidade: sub0 ≫ sub2 ≫ sub1/sub3 (Easy quase só on-beat) | **Lei** |
| R6 | Quando acorde vira single em Easy → preserva o **lowest fret** | Forte |
| R7 | Reduções são subconjuntos temporais do Expert (≥99.5%) | **Lei** |
| R8 | Acordes spread-alto são transpostos para a esquerda preservando shape; spread comprimido se necessário | Forte |
| R9 | Bursts são decimados ~25/50/75% (E/M/H), preferindo bordas e distribuição uniforme; pares 16th frequentemente sumindo no Easy | Forte |
| R10 | Hard preserva forma de acorde do Expert quando mantém o tick | **Lei** |
| R11 | Modo de sustain: melódico (preserva) vs agressivo (converte sustain curto em hit) — depende da música | Hipótese |
| R12 | Anchor de fret é **consequência**, não critério primário | Hipótese |

**Ainda a investigar (para Etapa 3 fechar):**
- HOPO/Tap: como se propagam entre dificuldades. → respondido em §7.7
- Star Power: marcador único da faixa, idêntico em todas dificuldades (já presumido pela estrutura MIDI; confirmar). → confirmado: pitch 116 vive na faixa, não na dificuldade
- "Anchor de seção" — a hipótese de que toda uma seção rítmica se ancora numa região do braço. → respondido em §7.8
- Como decidir entre **dropar acorde** (`→0`) vs **single** (`→1`) na Easy/Medium — possivelmente função do beat-position e da duração. → respondido em §7.9
- Critério para escolher o "modo de sustain" (R11) automaticamente — provavelmente densidade média do Expert ou predominância de notas curtas. → respondido em §7.10

### 7.7 Q7 — Propagação de HOPO/Tap (force-HOPO)

| Música | Force-HOPO ON+OFF por dificuldade |
|---|---|
| Aerials   | E:0 / M:0 / H:158 / X:186 |
| B.Y.O.B.  | 0 / 0 / 0 / 0 (não usa) |
| Chop Suey | 0 / 0 / 0 / 0 |
| Hypnotize | 0 / 0 / 0 / 0 |
| Spiders   | 1 / 1 / 33 / 45 |
| Toxicity  | 0 / 0 / 0 / 0 |
| Tap markers (pitch 104) | **zero em todas as 6 músicas** — RB-era charts não usam tap |

**→ R13 (forte):**
- Force-HOPO **ON é raríssimo** (a Harmonix usa quase só `force_hopo_off` para sobrescrever HOPOs automáticos do jogo).
- **Easy/Medium praticamente nunca recebem force-HOPO** — deixam a inferência automática do jogo decidir.
- **Hard pode receber uma fração** do Expert (Aerials: 158 dos 186 do Expert; Spiders: 33 dos 45).
- Não há tap markers nessas charts (eram da era RB1/2 antes do tap existir).

**Implicação prática:** ao gerar reduções, **omitir todos os force-HOPO** em E/M é um default seguro. No Hard, replicar os force-HOPO do Expert que caem em ticks que sobreviveram.

### 7.8 Q8 — Anchor de seção (deslocamento do fret-centroid em direção a G)

Janelas de 4 beats. `mean_shift_left` = quanto, em média, o centro-de-gravidade do fret nas notas da redução está deslocado para a esquerda em relação ao Expert (positivo = redução mais perto de G).

| Música | Easy | Medium | Hard |
|---|---|---|---|
| Aerials   | **+1.03** | +0.69 | −0.06 |
| B.Y.O.B.  | **+0.75** | −0.11 | −0.53 |
| Chop Suey | **+1.01** | +0.55 | −0.05 |
| Hypnotize | **+0.80** | +0.26 | −0.33 |
| Spiders   | **+0.85** | +0.27 | +0.25 |
| Toxicity  | **+0.59** | +0.44 | −0.10 |

**→ R14 (lei):** o centro-de-gravidade do braço desloca-se sistematicamente:
- **Easy:** ~+1 fret para a esquerda (consequência direta de R3: Easy só usa GRY).
- **Medium:** ~+0.4 fret para a esquerda (consequência de R4).
- **Hard:** neutro a levemente à direita (preserva o Expert; pode até ir +/- ao remover Greens isolados).

Isso significa: ao transpor um acorde do Expert (R8), o **alvo de fret-centroid** da seção/janela já está ditado pela dificuldade. O algoritmo deve **encontrar a transposição que minimiza a distância ao fret-centroid esperado**, dentro do conjunto de frets permitido na dificuldade.

### 7.9 Q9 — Drop-vs-single em Easy/Medium

Para acordes Expert que **não foram preservados como acorde**, computamos a probabilidade de virar single em vez de sumir. Buckets dominantes:

**Easy (sub0=on-beat, sub2=&, sub1/3=16ths fracos):**

| Bucket (sub, dur, contexto) | Single-rate observado |
|---|---|
| `(0, *, *)` on-beat                           | **0.5 – 1.0** (single dominante) |
| `(2, *, in_run)` & dentro de run rápido       | **0.00 – 0.15** (drop dominante) |
| `(2, *, isolated)` & isolado                  | **0.85 – 0.97** (single quase sempre) |
| `(1, *, *)` ou `(3, *, *)` 16ths fracos        | **≈ 0.0** (drop sempre) |
| `(0, '>=1/4', *)` on-beat e duração ≥ 1 beat  | **1.0** (single sempre) |

**Medium:**

| Bucket | Single-rate |
|---|---|
| `(0, *, *)` on-beat                           | preserva acorde ou single (não sumiu) |
| `(2, *, in_run)`                              | ~0.15–0.40 (mistura) |
| `(2, *, isolated)`                            | ~0.85–1.0 (single quase sempre) |
| `(1, *, *)` ou `(3, *, *)`                    | ≈ 0.0 (drop) |

**→ R15 (forte):**

```
def chord_outcome_easy(beat_position, duration, isolated):
    if beat_position == "sub0":      # on-beat
        return "single"               # quase sempre vira single (lowest fret)
    if beat_position == "sub2":       # & do beat
        return "single" if isolated else "drop"
    return "drop"                     # sub1/sub3 sempre dropa

def chord_outcome_medium(beat_position, duration, isolated):
    if beat_position == "sub0":
        return "preserve_or_single"   # o critério de preserve vs single é R8 (cabe na faixa de frets?)
    if beat_position == "sub2":
        return "single" if isolated else ("single" if random()<0.3 else "drop")
    return "drop"
```

(Em Hard, a regra dominante é simplesmente "preservar".)

### 7.10 Q10 — "Modo de sustain" (R11) — métrica de classificação

Métrica única por música:

| Música | total Expert | long ≥ 1/2 beat | ratio_long | **median_dur (ticks)** | mean_dur |
|---|---|---|---|---|---|
| Aerials   | 937  | 58  | 6.2%  | **120** | 136 |
| BYOB      | 1590 | 21  | 1.3%  | **120** | 111 |
| Chop Suey | 1052 | 48  | 4.6%  | **120** | 148 |
| Hypnotize | 756  | 46  | 6.1%  | **120** | 134 |
| Spiders   | 653  | 163 | 25.0% | **60**  | 148 |
| Toxicity  | 985  | 22  | 2.2%  | **80**  | 87  |

**→ R16 (forte):** Classifique a música pela `median_duration` do Expert:
- `median ≥ 100 ticks (≈ 1/4 beat)` → **modo melódico**: preserva sustains literais nas reduções (Aerials/BYOB/Chop Suey/Hypnotize).
- `median < 100 ticks` → **modo agressivo**: sustains intermediários (1/16-1/4 nota) viram **hits sem cauda** nas reduções (Spiders/Toxicity).

Detalhe: mesmo no modo agressivo, sustains genuinamente longos (≥ 1 beat) são preservados como sustain. Só os de duração intermediária convertem.

---

## 7. Convenções de cor / fret no jogo

```
0 = Green  (G)
1 = Red    (R)
2 = Yellow (Y)
3 = Blue   (B)
4 = Orange (O)
```

Open strum = nenhum botão de fret pressionado; representado como `frets=()` no parser.

---

## 8. Glossário rápido

- **Gem / nota / hit**: uma única ocorrência tocável na chart (pode ser single ou acorde).
- **HOPO** (Hammer-On / Pull-Off): nota tocada sem strum se vier rápido após outra de fret diferente.
- **Tap**: nota que pode ser tocada só pressionando o fret (sem strum), marcada por pitch 104.
- **Sustain**: nota com duração suficiente para mostrar "rabo" e dar pontos extras enquanto segurada.
- **Star Power / Overdrive**: trecho marcado pela pitch 116 que dobra pontos quando ativado.
- **BRE (Big Rock Ending)**: improviso de fim de música, marcado por pitches 120-124 em PART DRUMS.
- **Anchor**: prática do jogador de manter dedos baixos pressionados ao tocar notas mais altas — o chart pode pedir transições que respeitem ou quebrem isso.

---

## 9. Estado atual do trabalho

- ✅ **Etapa 1**: estrutura confirmada nas 6 músicas. Parser canônico funcionando.
- ✅ **Etapa 2**: dataset de alinhamento gerado, 10 sub-questões respondidas (§7.1–7.10). Regras R1–R17 documentadas em §6 e §8.
- ✅ **Etapa 3 — gerador v4 funcional + writer MIDI**: `_analysis/reducer.py` (gerador) + `_analysis/midi_writer.py` (escreve `notes.gen.mid`) + `_analysis/validate.py` (valida).
  - **Hard F1 = 0.85** (range 0.75–0.95)  ✓ excelente
  - **Medium F1 = 0.79** (range 0.67–0.95)  ✓ bom
  - **Easy F1 = 0.74** (range 0.65–0.92)  ✓ aceitável (deprioritizado pelo usuário)
  - **Expert preservado 100%** em todas as 6 músicas (recall=1.00, precision=1.00 vs original).
- 🔄 **Etapa 4 — possíveis melhorias futuras**:
  - F1 platô atual sugere que melhorias finas vão exigir features mais ricas (ex.: detecção de seção, padrões rítmicos, anchor de mão).
  - Densidade local por seção é a maior fonte de erro restante em Aerials Hard (perde 16ths reais do riff).
  - Transposição de acordes Easy power-chord (Chop Suey) ainda tem fret_exact ~0.28 — mapeamento mais preciso requer conhecimento musical de cada acorde.
- ⏳ **Etapa 5 — playtest no Clone Hero**: pendente. Os arquivos `notes.gen.mid` estão gerados em cada pasta de música. Falta abrir no jogo, jogar Hard/Medium/Easy e julgar manualmente a fluidez/playabilidade (F1 alto não garante feel correto).

### Tarefas internas registradas

(via TaskCreate; IDs podem mudar entre sessões)
- #1 Validar parsing de MIDI ✅
- #2 Construir dataset de redução Expert→inferiores ✅
- #3 Derivar heurísticas Harmonix ✅
- #4 Investigar HOPO/Tap/Sustain-threshold/Anchor por seção ✅
- #5 Implementar gerador `reduce_chart(expert, diff)` ✅
- #6 Validar gerador contra charts oficiais ✅
- #7 Refinar gerador v4 ✅
- #8 Implementar writer MIDI ✅

---

## 10. Decisões e preferências do usuário

- **Idioma:** responder em português; documentação em português.
- **Foco atual:** somente guitarra.
- **Música-base sugerida para deep-dive:** Chop Suey (cobre todos os tipos de passagem — power chords, riff de vozes, parte limpa, breakdown).
- **Nível de qualidade exigido:** equivalente à oficial Harmonix.
- O usuário pode fornecer tabs Guitar Pro multi-track se for útil — **não contar com isso por padrão**, mas pode ser pedido em momentos específicos.

---

## 11. Como continuar (instruções para a próxima LLM)

1. Leia este HANDOFF inteiro.
2. Rode `python3 _analysis/parse_chart.py` para confirmar que o parser ainda funciona no ambiente.
3. Veja qual etapa está marcada como ⏳ na seção 9.
4. Antes de implementar uma nova heurística, **busque em `_analysis/` se já existe um experimento sobre isso** — pode haver script ou CSV que economiza retrabalho.
5. **Toda nova descoberta vira nova entrada aqui**, com data se possível. Use ~~tachado~~ + correção para refutações.
6. Ao terminar uma sub-etapa, atualize a seção 9 (status) e crie/atualize tasks via TaskCreate/TaskUpdate.

---

## 12. Log de mudanças

- **2026-04-21 (1)** — Documento inicial criado. Etapa 1 concluída: estrutura MIDI confirmada nas 6 músicas, parser canônico em `_analysis/parse_chart.py`, primeiras estatísticas e regras candidatas R1–R4 + hipóteses H1–H2 documentadas.
- **2026-04-21 (2)** — Etapa 2 iniciada. Adicionados `_analysis/align.py` e `_analysis/deep_dive.py` + `_analysis/alignment_report.json`. Documentadas seções §7.1–7.6 com novas regras R5–R12.
- **2026-04-21 (3)** — Etapa 2 concluída. Adicionado `_analysis/finer.py`. Seções §7.7–7.10 documentadas com R13–R16.
- **2026-04-21 (4)** — ~~R1 lei "Easy = sem acordes"~~ refutada por Chop Suey Easy (116 acordes). Substituída por **R17**. Adicionado `_analysis/reducer.py` (gerador v1→v3) e `_analysis/validate.py`. F1 inicial: Hard 0.83 / Medium 0.74 / Easy 0.63.
- **2026-04-22 (5)** — Etapa 3 + writer MIDI (Etapa 4) concluídos. Gerador v4 com:
  - **target_density adaptativo** via regressão linear `target = a + b*notes_per_beat + c*sub0_ratio` (RMSE ~0.03 em Easy/Medium nas 6 músicas treino) — substituiu o target fixo do v3.
  - **Decimação por janela de 1 beat** com cap (Easy=1, Medium=3, Hard=6) e fallback para sustain longo.
  - **Score function**: sub0=100, sub2=60, sub1/3=5 (35 em Hard); +120 sustain ≥2 beats / +80 ≥1 / +40 ≥1/2; bonus borda-de-run, isolamento, mudança de fret.
  - **Shift por janela**: shift=-1 quando centroid Expert ≥ 1.5 (Easy ou Medium) — captura Hypnotize Medium (que toda fica -1 fret).
  - **R17 implementada**: Easy aceita pwr-chord (≤2 notas, spread ≤ 3) quando música está em modo power-chord, com shift -1.
  - **R16 implementada**: modo "agressivo" → sustains < 1 beat viram hits sem cauda em E/M.
  - **Writer MIDI** (`midi_writer.py`): gera `notes.gen.mid` em cada pasta, preservando todas as faixas originais e o Expert intacto. **Validado: Expert preservado 100% nas 6 músicas.**
  - **Resultados finais F1:** Hard **0.85**, Medium **0.79**, Easy **0.74**.
- **2026-04-22 (6)** — Validação subjetiva pelo usuário no Moonscraper: **Hypnotize Hard+Medium "perfeito"**. **Aerials "nada a ver"**. Iteração para subir Aerials revelou:
  - Aerials Expert é **tremolo escalar circular de 4 notas/beat** (G→B→O→Y/B→O→G→B...) — 171 dos 295 beats têm 4 notas consecutivas em 16ths.
  - Aerials Hard oficial preserva ~2.27 notas/beat (mistura de 1, 2, 3 notas) com **5 padrões diferentes** de retenção (sub0+sub2 dominante, mas com variantes para preservar transições musicais).
  - Aerials Medium oficial é **motivo melódico extremamente específico** (1 nota por beat, escolhida pela melodia, não pelo sub-beat). F1 difícil de melhorar via score function genérica.
  - Tentadas: alocação Bresenham (piorou Hypnotize), regra forçada sub0+sub2 (não mudou), target_ratio local por janela (piorou outras), peak-fret bonus (pequena melhora geral).
  - **Conclusão:** Aerials é caso "sem padrão estatístico" — para subir além do platô requer features de **detecção de motivo melódico/repetição** ou modelo treinado nota a nota. Adicionado **R18** (peak-fret bonus em Hard/Medium): score +25/+15 para nota cujo fret é máximo dentro do beat (preserva picos do tremolo).
  - **F1 final pós-iteração:** Hard 0.85, Medium 0.79, Easy 0.74 (mesmo platô; melhoria pequena de fret_exact em Hard).
- **2026-04-22 (7)** — Início do estudo de **PART DRUMS** (bateria). Criado `_analysis/parse_drums.py`. Documentada nova **§14** com mapa de pitches, Pro Drums, convenção musical, estatísticas brutas e regras D-R1 a D-R7 candidatas.
- **2026-04-22 (8)** — Drums completa: análise + reducer + writer MIDI estendido.
  - `_analysis/align_drums.py`: alinhamento Expert↔reduções, validou D-R1 a D-R12.
  - **Achados-chave do alinhamento:**
    - **D-R3 refinada (LEI):** Em Easy/Medium, kick só é mantido se simultâneo a outra nota. Solo kicks dropam ~100%.
    - **D-R7 confirmada (LEI):** 2x kick (pitch 95) some 100% em E/M/H.
    - **D-R8 (forte):** Snare em Easy ≈ Snare em Medium (mesma redução em 5/6 músicas).
    - **D-R9 (NOVA, forte):** Drums permite **transferência entre lanes** na redução. Padrões: Blue-tom raro → Yellow-tom em E/M; Green-cym → Blue-cym em Hard; Green-cym → Blue-tom em E/M.
    - **D-R10 (forte):** Em Hard, Green-cym tende a virar Blue-cym (visto em Hypnotize: 48 de 49 Green-cym Expert viraram Blue-cym Hard).
    - **D-R11 (forte):** Yellow-cym preservada ~95-100% em Hard.
  - `_analysis/reducer_drums.py`: targets calibrados via regressão; aplica D-R1 a D-R12.
  - `_analysis/midi_writer.py` estendido: gera PART GUITAR + PART DRUMS no mesmo notes.gen.mid.
  - **Resultados drums F1:** Hard **0.86** / Medium **0.75** / Easy **0.62**. Expert preservado 100% para ambas PARTs.

---

## 13. Mudanças nas regras vs versão inicial

| Regra | Status | Motivo |
|---|---|---|
| ~~R1 (Easy = sem acordes)~~ | **refutada** em 2026-04-21 (4) | Chop Suey Easy tem 116 acordes (sizes={1:157,2:116}). Substituída por R17. |
| R17 | **nova** | Easy aceita acordes (≤2 notas, GRY, spread≤2) quando música está em "modo power-chord". |
| H1 (densidade fixa por dificuldade) | **refinada** | A variação por música é grande (Easy/X varia de 16% Hypnotize a 29% Spiders). Target médio (~22/38/65%) ainda é a melhor base. |
| H2 (sustains longos preservados) | **confirmada como R11/R16** | Limiar prático: sustain ≥ 1 beat sempre preservado; 1/8-1 beat depende do "modo da música". |
| H4 (anchor é consequência) | **confirmada** | Mean repeat varia 1.2-3.7 sem padrão consistente E/M/H. |

---

## 14. PART DRUMS — análise estrutural

Documenta tudo sobre a chart de bateria. Análise focada em **descrever** o formato e padrões observados nas 6 músicas SOAD; **construção do reducer de drums fica para a próxima etapa**.

### 14.1 Mapa de pitches (PART DRUMS)

| Dificuldade | Kick | Snare (R) | Yellow (Y) | Blue (B) | Green (G) |
|---|---|---|---|---|---|
| Easy   | 60 | 61 | 62 | 63 | 64 |
| Medium | 72 | 73 | 74 | 75 | 76 |
| Hard   | 84 | 85 | 86 | 87 | 88 |
| Expert | 96 | 97 | 98 | 99 | 100 |

**Pitch 95 = 2x bass pedal (Expert+)** — kick adicional para "double bass" mode (visto em BYOB com 99 ocorrências).

**Marcadores compartilhados pela faixa:**

| Pitch | Função |
|---|---|
| 110 | **Yellow TOM marker**: durante este intervalo, Y = tom. **Fora do intervalo, Y = prato (hi-hat) por padrão.** |
| 111 | **Blue TOM marker**: durante este intervalo, B = tom. Fora, B = prato (ride). |
| 112 | **Green TOM marker**: durante este intervalo, G = tom (surdo). Fora, G = prato (crash). |
| 105/106 | Player 1/Player 2 markers (RB1) |
| 116 | Overdrive / Star Power |
| 120-124 | Drum fill / BRE — 5 pitches simultâneos = 1 drum fill |
| 24-51 | Animações (kick foot, sticks, hands) — IGNORAR para chart |
| 12, 14 | Trainer/practice markers |

**Velocity:** todas as notas dessas charts SOAD usam `vel=100`. RB3+ usa vel=127 (accent) e vel=1-50 (ghost) — **não aparece nas SOAD**. Provavelmente charts de era pré-RB3.

**Text events em PART DRUMS:**
- `[mix N drumsK...]` — sincroniza qual stem de áudio toca (auto-mix). N = dificuldade (0-3 = E/M/H/X), K = configuração (`drums3`, `drums3easy`, `drums3easynokick`...). Não afeta chart de notas.
- `[idle]`, `[intense]`, `[play]` — drummer animation cues. Ignorar.

### 14.2 Pro Drums — diferenciação tom/cymbal

> **Correção 2026-04-22:** a versão inicial deste documento tinha a convenção invertida. A convenção real RBN/CH é: Y/B/G são **pratos por padrão**; os pitches 110/111/112 são **tom markers** que convertem a cor em tom apenas no intervalo em que estão ativos. Verificado visualmente no Moonscraper: o início de Hypnotize (sem markers 110) aparece como hi-hat amarelo.

**Como funciona:** os pitches 110, 111, 112 são "phrase markers" — quando ON, **todas as notas Yellow/Blue/Green** que acontecem dentro daquele intervalo (em Hard/Expert) são interpretadas como **prato** ao invés de **tom**. Quando OFF, são tom.

**Convenção musical** (cortesia do usuário):
- **Vermelho** (61/73/85/97) = caixa
- **Yellow tambor** = tom 1 (high tom)
- **Yellow prato** = chimbal (hi-hat fechado normalmente)
- **Blue tambor** = tom 2 (mid tom)
- **Blue prato** = ride; **às vezes representa hi-hat aberto** quando o resto está em fechado; raramente prato de ataque
- **Green tambor** = surdo (floor tom)
- **Green prato** = crash; pode aparecer em sequência (vários crashes seguidos)
- **Pedal** (60/72/84/96) = bumbo

**Importante:** Pro Drums só existe em **Hard e Expert**. Em **Easy/Medium**, todas as Y/B/G são **lane (sem distinção tom/cymbal)** — visualmente mostradas como tambor. **Nas 6 músicas SOAD: 0 cymbals em Easy e 0 em Medium**.

### 14.3 Estatísticas brutas (geradas por `_analysis/parse_drums.py`)

```
Aerials
  Easy   total= 445  {Snare:124, Kick:58,  Y-tom:29,  B-tom:189, G-tom:45}
  Medium total= 769  {Snare:124, Kick:129, Y-tom:271, B-tom:198, G-tom:47}
  Hard   total= 949  {Snare:151, Kick:229, Y-tom:243, Y-cym:45, B-tom:209, B-cym:17, G-tom:51, G-cym:4}
  Expert total=1195  {Snare:170, Kick:276, Y-tom:415, Y-cym:47, B-tom:210, B-cym:18, G-tom:51, G-cym:8}

B.Y.O.B.
  Easy   total= 707  {Snare:279, Kick:18,  Y-tom:292, B-tom:6,   G-tom:112}
  Medium total= 958  {Snare:283, Kick:161, Y-tom:386, B-tom:6,   G-tom:122}
  Hard   total=1637  {Snare:310, Kick:402, Y-tom:557, Y-cym:20, B-tom:143, B-cym:7, G-tom:198}
  Expert total=2324  {Snare:431, Kick:823, Y-tom:690, Y-cym:25, B-tom:165, B-cym:14, G-tom:176}

Chop Suey
  Easy   total= 661  {Snare:125, Kick:25,  Y-tom:129, B-tom:338, G-tom:44}
  Medium total= 821  {Snare:129, Kick:119, Y-tom:162, B-tom:341, G-tom:70}
  Hard   total=1094  {Snare:161, Kick:220, Y-tom:229, Y-cym:30, B-tom:347, B-cym:30, G-tom:63, G-cym:14}
  Expert total=1295  {Snare:163, Kick:335, Y-tom:274, Y-cym:46, B-tom:348, B-cym:52, G-tom:63, G-cym:14}

Hypnotize
  Easy   total= 443  {Snare:75,  Kick:44,  Y-tom:140, B-tom:132, G-tom:52}
  Medium total= 627  {Snare:75,  Kick:104, Y-tom:308, B-tom:84,  G-tom:56}
  Hard   total= 888  {Snare:80,  Kick:182, Y-tom:325, Y-cym:109, B-cym:125, G-tom:67}
  Expert total=1502  {Snare:84,  Kick:313, Y-tom:538, Y-cym:113, B-tom:4, B-cym:314, G-tom:87, G-cym:49}

Spiders
  Easy   total= 396  {Snare:106, Kick:14,  Y-tom:219, B-tom:1,   G-tom:56}
  Medium total= 534  {Snare:106, Kick:90,  Y-tom:281, B-tom:1,   G-tom:56}
  Hard   total= 706  {Snare:170, Kick:183, Y-tom:280, Y-cym:1, B-cym:1, G-tom:71}
  Expert total= 883  {Snare:265, Kick:256, Y-tom:273, Y-cym:2, B-tom:32, B-cym:1, G-tom:54}

Toxicity
  Easy   total= 552  {Snare:198, Kick:90,  Y-tom:138, B-tom:18,  G-tom:108}
  Medium total= 968  {Snare:218, Kick:113, Y-tom:463, B-tom:38,  G-tom:136}
  Hard   total=1357  {Snare:338, Kick:265, Y-tom:278, Y-cym:111, B-tom:164, B-cym:41, G-tom:160}
  Expert total=1650  {Snare:456, Kick:402, Y-tom:281, Y-cym:107, B-tom:167, B-cym:79, G-tom:158}
```

### 14.4 Densidades por dificuldade (drums)

Razão `notas_E_M_H / notas_Expert`:

| Música | Easy/X | Medium/X | Hard/X |
|---|---|---|---|
| Aerials   | 0.37 | 0.64 | 0.79 |
| BYOB      | 0.30 | 0.41 | 0.70 |
| Chop Suey | 0.51 | 0.63 | 0.84 |
| Hypnotize | 0.30 | 0.42 | 0.59 |
| Spiders   | 0.45 | 0.60 | 0.80 |
| Toxicity  | 0.33 | 0.59 | 0.82 |
| **Média** | **0.38** | **0.55** | **0.76** |

**Comparação com guitarra** (média): E=0.23, M=0.38, H=0.64.

**→ Conclusão D1:** Bateria preserva muito mais que guitarra em todas as dificuldades — porque "simplificar bateria" é mais sobre **tirar pratos**, **fundir tons** e **diminuir kick**, não tanto sobre dropar gem-events. O ritmo central é preservado.

### 14.5 Regras de redução observadas (drums)

**D-R1 (Lei): Easy e Medium NÃO TÊM CYMBAL.** Confirmado nas 6 músicas (0 cymbals). Todos os Y/B/G de Easy/Medium são "tom". Conversão: cymbal Hard/Expert vira tom da mesma cor em Medium/Easy (preservando a lane).

**D-R2 (Lei): Snare é sagrada.** Snare é a coluna vertebral do ritmo. Razões Easy/Snare-X variam 40%–89% — sempre alta retenção comparada a outras lanes.

**D-R3 (forte): Kick é fortemente decimado em Easy.** Razão Easy-kick / Expert-kick:
- BYOB: 18 / 823 = **2%** (drasticamente reduzido)
- Hypnotize: 44 / 313 = 14%
- Spiders: 14 / 256 = 5%
- Aerials: 58 / 276 = 21%
- Chop Suey: 25 / 335 = 7%
- Toxicity: 90 / 402 = 22%
A regra parece ser: **Easy mantém kick só nos downbeats fortes** (geralmente sub0 do beat 1 do compasso, ou momentos enfáticos).

**D-R4 (forte): Em Medium, kick mantém ~30-40% do Expert.** Reduz mas mantém mais que Easy.

**D-R5 (forte): "Linhas duplas" (kick simultâneo com snare/tom) são geralmente preservadas em todos os níveis** — o "downbeat fundamental" não é dropado. Hipótese, validar.

**D-R6 (hipótese): Em Hard, cymbal Expert pode virar tom da mesma cor** se a região está saturada de cymbals. Validar com inspeção.

**D-R7 (hipótese): 2x kick (pitch 95, double bass) é simplificado para single kick (pitch 96) em Hard, e some completamente em Medium/Easy.** Validar olhando BYOB (que tem 99 ocorrências do pitch 95).

### 14.6 Alinhamento Expert↔reduções (drums) — achados

Análise rodada por `_analysis/align_drums.py`. Validou várias hipóteses e descobriu novas regras.

#### 14.6.1 Confirmação D-R3 → REFINADA: Kick em E/M é SEMPRE paired

Para cada música, 100% dos kicks mantidos em **Easy** estão em ticks que **também têm outra nota** (snare, tom, cymbal). Kicks "solo" (isolados) são dropados ~100% do tempo.

| Música | Easy: paired_kept / solo_kept | Medium: paired_kept / solo_kept | Hard: paired_kept / solo_kept |
|---|---|---|---|
| Aerials   | 58 / 0  | 129 / 0 | 165 / 64 |
| BYOB      | 17 / 1  | 160 / 1 | 356 / 46 |
| Chop Suey | 25 / 0  | 119 / 0 | 207 / 13 |
| Hypnotize | 44 / 0  | 104 / 0 | 169 / 13 |
| Spiders   | 14 / 0  | 90 / 0  | 175 / 8 |
| Toxicity  | 90 / 0  | 113 / 0 | (igual) |

**→ D-R3 (Lei refinada):** Em **Easy e Medium**, kick só é mantido se **simultâneo a outra nota** (snare/tom/cym). Em **Hard**, kicks solo podem aparecer (mas ainda minoritários).

#### 14.6.2 Confirmação D-R7: 2x kick desaparece

BYOB tem **99 ocorrências de 2x kick** (pitch 95). Em **Easy: 0 mantidos. Medium: 0. Hard: 0**. **→ D-R7 (Lei) confirmada.**

#### 14.6.3 Snare Easy ≡ Snare Medium na maioria

| Música | Snare Easy | Snare Medium |
|---|---|---|
| Aerials   | 124 | 124 (idêntico) |
| BYOB      | 279 | 283 (quase) |
| Chop Suey | 125 | 129 (quase) |
| Hypnotize | 75  | 75  (idêntico) |
| Spiders   | 106 | 106 (idêntico) |
| Toxicity  | 198 | 218 |

**→ D-R8 (forte):** Snare em Easy e Medium é tipicamente o mesmo subset. A simplificação E vs M acontece em outras lanes.

#### 14.6.4 Transferência entre lanes — DROPS por reorganização visual

**Achado importante**: drums permite **mudança de lane** na redução, não apenas drop.

Casos observados:
- **BYOB Easy/Medium**: Blue-tom Expert → **Yellow-tom** Easy/Medium em ~85% dos casos. A música tem poucos Blue-tom, então a Harmonix consolida para Yellow.
- **Hypnotize Hard**: Green-cym Expert → **Blue-cym** Hard em **48 dos 49 casos** (98%). Crash distante é convertido para ride/hi-hat aberto mais central.
- **Hypnotize Easy/Medium**: Green-cym Expert (49) → **Blue-tom** Easy/Medium em 45/49. Cymbal vira tom da lane mais ativa musicamente, não da mesma cor.
- **Toxicity Easy**: Blue-tom Expert → Yellow-tom* (76) ou Snare* (52). Consolidação visual.

**→ D-R9 (forte, NOVA):** A Harmonix consolida lanes pouco usadas em redução. Padrões observados:
- **Blue-tom isolado/raro → Yellow-tom** (B→Y) em E/M.
- **Green-cym → Blue-cym** em Hard (cymbal aproxima do centro).
- **Green-cym → Blue-tom** em E/M (cymbal vira tom da lane musical mais usada, não da própria cor).

#### 14.6.5 Conversão cymbal→tom em E/M (D-R1 detalhado)

Para cada Y-cym/B-cym/G-cym Expert que sobrevive em Easy/Medium:

| Cymbal Expert | E/M outcome típico |
|---|---|
| Yellow-cym | ~50% vira **Yellow-tom**, ~50% drop |
| Blue-cym | ~30% vira **Blue-tom**, ~70% drop |
| Green-cym | ~50% vira **Blue-tom** (não Green-tom!), ~50% drop |

**→ D-R1.1:** Em E/M, conversão preferencial é cymbal → tom da MESMA COR, exceto Green-cym que prefere Blue-tom (a lane mais ativa).

#### 14.6.6 Conversão em Hard

| Item Expert | Hard outcome típico |
|---|---|
| Yellow-cym | **95-100% mantém Yellow-cym** (D-R11) |
| Blue-cym  | 24% (Hypnotize) a 94% (Aerials) mantém Blue-cym; resto drop |
| Green-cym | Variável. Hypnotize: 98% vira Blue-cym (D-R10). Chop Suey: 100% mantém Green-cym. |
| Y-tom/B-tom/G-tom | 60-100% mantém lane idêntica |
| Snare | 60-99% mantém |
| Kick | 50-85% mantém (paired ou solo) |

**→ D-R10 (forte):** Em Hard, **Green-cym tende a virar Blue-cym** quando densidade de Green-cym é alta na música (Hypnotize tinha 49). Quando rara (Chop Suey 14), pode preservar.

**→ D-R11 (forte):** **Yellow-cym é preservada** quase sempre em Hard.

### 14.7 Lista consolidada de regras drums (para implementação)

| ID | Regra | Força |
|---|---|---|
| D-R1 | Easy e Medium = ZERO cymbals (todos viram tom ou some) | **Lei** |
| D-R1.1 | Cymbal Expert → tom da mesma cor em E/M, exceto Green-cym → Blue-tom | Forte |
| D-R2 | Snare é "sagrada": mantém lane Snare em todos os níveis | **Lei** |
| D-R3 | Em Easy/Medium, kick só é mantido se **simultâneo a outra nota** (snare/tom/cym) | **Lei** |
| D-R4 | Densidades: kick E ~5-22%, M ~20-50%, H ~50-90% (varia por música) | Forte |
| D-R7 | 2x kick (pitch 95, Expert+) some 100% em Hard/Medium/Easy | **Lei** |
| D-R8 | Snare em Easy ≈ Snare em Medium (mesma redução) | Forte |
| D-R9 | Lanes pouco usadas são consolidadas: Blue-tom raro → Yellow-tom em E/M; Green-cym → Blue-cym em Hard ou Blue-tom em E/M | Forte |
| D-R10 | Em Hard, Green-cym tende a virar Blue-cym (especialmente quando >30 ocorrências) | Forte |
| D-R11 | Yellow-cym é preservada em Hard (~95-100%) | **Lei** |
| D-R12 | Em todos os níveis, drum_fills (120-124) são preservados intactos | Forte (a verificar) |

### 14.8 Reducer drums — implementação e validação

`_analysis/reducer_drums.py` implementa pipeline de redução com:
- **Targets por lane** calibrados via regressão linear nas 6 músicas:
  - `TOM_RATIOS[diff][lane]`: kept_count = ratio * expert_count
  - `CYMBAL_RATIOS_HARD`: Y=0.93, B=0.46, G=0.25 (Yellow preserva, Blue/Green decimam)
  - `CYMBAL_TO_TOM_FRACTION` em E/M: 20% (Easy), 30% (Medium) — fração que sobrevive como tom
- **D-R3 implementada**: kick em E/M filtrado para só notas paired
- **D-R7 implementada**: 2x kick (pitch 95) sempre dropado em E/M/H
- **D-R9 implementada**: detect_lane_consolidation — Blue→Yellow quando blue raro OU Y-cym presente >50
- **D-R10 implementada**: detect_green_cym_strategy — G-cym→Blue-cym em Hard quando >30 ocorrências

**Resultados F1 (incluindo cymbal vs tom no match):**

| Música | Hard | Medium | Easy |
|---|---|---|---|
| Aerials   | **0.88** | 0.82 | 0.62 |
| BYOB      | **0.90** | 0.74 | 0.63 |
| Chop Suey | **0.91** | 0.79 | 0.74 |
| Hypnotize | 0.80 | 0.66 | 0.50 |
| Spiders   | 0.82 | 0.78 | 0.63 |
| Toxicity  | 0.83 | 0.70 | 0.57 |
| **Média** | **0.86** | **0.75** | **0.62** |

**Comparação com guitarra (mesma escala):** Hard 0.85 / Medium 0.79 / Easy 0.74. Bateria comparable em Hard, ligeiramente abaixo em Easy/Medium — devido à **transferência inter-lane** ser mais difícil de modelar que a redução de chord-shape da guitarra.

### 14.9 Writer MIDI estendido para drums

`_analysis/midi_writer.py` agora gera **PART GUITAR + PART DRUMS** no mesmo `notes.gen.mid`:
- Strip pitches 60-64 / 72-76 / 84-88 (E/M/H drums)
- Preserva: Expert (96-100), 2x kick (95), Pro Drums markers (110/111/112), SP (116), drum fills (120-124), animações (24-51), P1/P2 (105/106), text events
- Adiciona notas geradas por `reduce_drums()` na pitch correta de cada lane/dificuldade
- **Validado: Expert intacto 100% nas 6 músicas para ambas PARTs.**

### 14.10 Overrides por preferência do usuário (2026-04-22)

Após validação visual, o usuário pediu **dois desvios das regras observadas**:

**Override 1: Cymbal preservado em Easy/Medium** (sobrescreve D-R1)
- Charts oficiais Harmonix convertem cymbal Expert → tom em E/M (Pro Drums só em Hard/Expert).
- O usuário prefere que cymbal Expert **continue cymbal em E/M**, com a mesma frequência da regra atual (target_lane * 0.7 dos cymbals Expert).
- Implicação: o jogador em Pro Drums mode verá pratos em E/M (depende do CH suportar — o marker 110/111/112 já é preservado pelo writer).

**Override 2: Anti-16ths-consecutivos em Easy/Medium/Hard**
- Qualquer **par** de notas mesma lane com gap ≤ 1/16 nota (=tpb/4) é considerado "rápido demais" para E/M/H — só Expert tolera 16ths consecutivos.
Espaçamento mínimo entre notas mantidas (greedy temporal):
- **Easy:** 1/4 (semínima) para todos.
- **Medium:** 1/8 (colcheia) para todos.
- **Hard:** **1/16** para tambores Y/B/G, kick e snare; só pratos ficam limitados a 1/8 — preferência do usuário 2026-04-22. Em Hard, tambores Y+B+G ainda são tratados como uma única voz (preserva viradas Y-B-G em 16ths).
- Não afeta snare (D-R2 sagrada) nem kick (já decimado por D-R3).
- Caso disparador: início de Hypnotize tem amarelo 16ths que o oficial mantém integral em Hard, mas o usuário considerou "muito rápido pro Hard".

Implementação em `_analysis/reducer_drums.py`:
- Função `filter_fast_clusters()` aplicada após seleção principal.
- F1 vs charts oficiais cai em algumas músicas (esperado — o gerador agora **diverge intencionalmente** do oficial).

### 14.11 Próximos passos drums

1. ✅ Análise estrutural + reducer + writer MIDI.
2. ✅ Overrides por preferência do usuário.
3. ⏳ Validação subjetiva no Moonscraper.
4. ⏳ Possíveis melhorias futuras: snare ratio adaptativo, fills inteiros preservados em E/M, rolls/swells.
