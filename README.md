# Songsterr Drum Import

> Este arquivo e a fonte canonica de handoff para o import de bateria do Songsterr.
> projeto esta descrito aqui e deve prevalecer sobre qualquer documento antigo.

## 1. Objetivo

Gerar uma `PART DRUMS` Expert para Clone Hero a partir de um MIDI do Songsterr,
alinhando a bateria ao tempo real da chart de referencia.

Cenario real de producao:

- a pasta da musica ja tem `notes.chart` ou `notes.mid` sincronizado ao audio
- normalmente existe `PART GUITAR`, mas nao `PART DRUMS`
- o Songsterr fornece o MIDI fonte com a bateria em GM no canal 9
- o resultado final deve ser salvo como `notes.songsterr.mid`

A verdade temporal final e sempre a chart de referencia. O MIDI do Songsterr
so fornece a estrutura musical e os anchors de compasso.

## 2. Arquivos canonicos

Pipeline principal:

- `_analysis/parse_chart.py`
- `_analysis/parse_drums.py`
- `_analysis/import_songsterr.py`
- `_analysis/songsterr_import/context.py`
- `_analysis/songsterr_import/pipeline.py`
- `_analysis/songsterr_import/measure_marker_sync.py`
- `_analysis/songsterr_import/source.py`
- `_analysis/songsterr_import/mapping.py`
- `_analysis/songsterr_import/writer.py`
- `_analysis/songsterr_import/constants.py`

Scripts auxiliares:

- `_analysis/postprocess_bubbles_songsterr.py`
- `_analysis/postprocess_soldier_side_songsterr.py`
- `_analysis/fix_soldier_side_songsterr_mid.py`
- `_analysis/generate_measure_debug_songsterr.py`
- `sync_to_whisky.sh`

## 3. Comando de producao

Uso basico:

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>"
```

Flags ativas hoje:

```bash
python3 _analysis/import_songsterr.py "<songsterr.mid>" "<out.mid>" \
  --ref-path "<notes.chart|notes.mid>" \
  --initial-offset-ticks 768 \
  --drop-before-src-beat 0 \
  --dedup-beats 0.0625 \
  --minimum-snare-velocity 75
```

Semantica atual das flags:

- `--ref-path`: override explicito da chart de referencia
- `--initial-offset-ticks`: offset global aplicado depois do mapeamento por compassos
- `--drop-before-src-beat`: descarta hits do source antes desse beat
- `--dedup-beats`: janela usada para flam de snare e dedup de outras lanes
- `--minimum-snare-velocity`: filtra apenas caixas abaixo do valor; se omitido,
  todas as caixas entram

Auto-deteccao de referencia:

- `notes.chart`
- `notes.mid`

O importer procura esses arquivos no diretorio do `src_mid`, do `out_mid` e do
`--ref-path` quando existe. Se nao achar referencia valida, falha com erro.

## 4. Modelo de sync em producao

O pipeline ativo usa apenas `MEASURE_n`.

### 4.1 Fonte dos anchors

- `_source_measure_marker_ticks()` le os markers `MEASURE_n` da track de bateria
  escolhida no Songsterr
- `measure_start_ticks()` calcula os inicios de compasso da referencia a partir
  dos `time_signature` reais do conductor

Isso suporta naturalmente musicas com mudanca de formula de compasso:

- `4/4`
- `7/8`
- `9/8`
- `5/4`
- `3/4`
- `6/8`

Se o Songsterr nao tiver markers `MEASURE_n` suficientes na track de bateria, o
pipeline deve falhar. Nao existe fallback silencioso.

### 4.2 Warp por compasso

`_build_adaptive_measure_anchors()` compara a duracao real, em segundos, de:

- 1 compasso do source
- 1 compasso da referencia
- 2 compassos consecutivos da referencia

Se 2 compassos da referencia casarem melhor com 1 compasso do source por uma
margem real de pelo menos `0.05s`, o importer usa um pareamento `1x -> 2x`.
Nesse caso ele cria um anchor sintetico no meio do compasso do source para
interpolar a metade correspondente.

Esse comportamento existe para casos como o interludio de `Sugar`.

### 4.3 Offset inicial

`DEFAULT_INITIAL_OFFSET_TICKS = 768`.

O offset inicial nao e mais somado cegamente a todos os ticks da referencia.
Ele e interpretado como:

- quantos compassos inteiros da chart devem ser pulados
- mais um residuo fino em ticks

Charts que tem um compasso extra no comeco pois é assim que é o formato esperado no Clone Hero, por isso que usamos 768, que é exatamente um compasso.

Casos reais que validaram essa regra:

- `Soil`: alternancia `4/4` e `7/8`
- `Question!`: alternancia `9/8`, `5/4`, `3/4` e `4/4`

Nos logs do importer isso aparece como:

- `offset manual=+768 ticks (pula 1 compassos da chart)`

### 4.4 Interpretacao correta do tempo

Nao confie em BPM nominal puro.

A mesma musica pode ser escrita com:

- formulas de compasso diferentes
- BPMs aparentes diferentes
- mesma duracao musical real

O que importa e:

- os anchors musicais do source
- o mapa temporal final da chart de referencia

## 5. Selecao da track de bateria

`select_source_drum_track()` nao escolhe a primeira track do canal 9.

Ela ranqueia candidatos por:

- quantidade de hits mapeaveis
- hint de nome (`drum`, `kit`, `perc`, `percussion`)
- quantidade total de hits no canal 9
- ordem da track

Se existir um candidato de bateria real, tracks auxiliares de `perc` /
`percussion` sao descartadas do ranking final.

Isso e importante para MIDIs com:

- duas tracks de bateria
- uma track principal e outra de acompanhamento/percussao

## 6. Mapeamento atual de notas GM -> CH

### 6.1 Notas mapeadas diretamente

- `35`, `36` -> kick
- `37`, `38`, `40` -> snare
- `42` -> yellow cymbal
- `46` -> yellow cymbal por padrao
- `49` -> green cymbal
- `51` -> blue cymbal
- `52` -> green cymbal
- `53` -> blue cymbal
- `55` -> blue cymbal
- `56`, `67`, `68` -> blue cymbal
- `57` -> green cymbal

Chokes / variantes:

- `17` High Crash (Choke) -> green cymbal
- `18` Medium Crash (Choke) -> green cymbal
- `19` China (Choke) -> green cymbal
- `20` Ride Cymbal (Choke) -> blue cymbal
- `21` Splash (Choke) -> blue cymbal

### 6.2 Notas ignoradas globalmente

- `39` Hand Clap -> ignorado
- `44` Foot Hi Hat -> ignorado
- qualquer pitch sem mapeamento -> ignorado

### 6.3 Toms nominais

Base atual:

- `41`, `43`, `45` -> green tom
- `47` -> blue tom
- `48`, `50` -> yellow tom

### 6.4 Heuristicas de tom

`build_tom_pitch_map()` e `build_tom_lane_overrides()` fazem dois ajustes
importantes:

1. **Lowered kit adaptativo**

Se a musica nao usa toms altos (`48` ou `50`), o kit baixo e reescalado assim:

- maior pitch presente do grupo baixo -> yellow
- segundo maior -> blue
- restantes -> green

2. **Viradas de low tom**

Se uma corrida contem apenas low toms e nao vem de uma sequencia com upper tom
antes, o maior low tom da corrida vira blue e o menor vira green. Isso deixa
fills `floor -> very low` mais legiveis no CH.

## 7. Regras atuais de hihat / prato

### 7.1 Open hihat

`46` e yellow por padrao.

Ele so vira blue quando:

- esta entre dois `42`
- os gaps anterior e posterior sao equilibrados
- e nao faz parte de uma alternancia mais longa de open hats

Isso modela o caso "open isolado entre closed hats".

### 7.2 Closed hihat que deve sumir

O closed `42` e descartado quando:

- aparece entre dois `46`
- os gaps anterior e posterior sao equilibrados

Na pratica, uma sequencia como:

- `46, 42, 46`

vira:

- `Y, (drop), Y`

Numa alternancia maior como:

- `46, 42, 46, 42`

o open continua yellow e o closed do meio some. Isso evita transformar esse
padrao em uma parede azul.

## 8. Flam, dedup e filtros de snare

### 8.1 Janela de dedup

`--dedup-beats` vale `1/16 beat` por padrao.

Para hits na mesma lane dentro dessa janela:

- snare -> trata como flam
- outras lanes -> remove a segunda nota

### 8.2 Flam de snare

Quando duas caixas caem na janela de dedup:

- a primeira caixa vermelha e preservada
- a segunda vira um yellow tom simultaneo no tick da primeira

Implementacao real:

- `snare_flam_second_to_first` guarda o mapeamento do segundo hit para o tick
  do primeiro
- o writer escreve o segundo hit como yellow tom no mesmo tick
- o primeiro snare e explicitamente removido de `skipped_weak_snares` para que o
  flam nunca vire "só amarelo"

### 8.3 Filtro de velocity de caixa

`--minimum-snare-velocity` e opcional.

Comportamento atual:

- se **omitido**, todo hit com `velocity > 0` entra
- se **passado**, apenas a familia de snare (`37`, `38`, `39`, `40`) abaixo do
  threshold e descartada
- outras pecas nunca usam esse threshold

Valor historico util:

- `75`

### 8.4 Weak snare

O descarte de `weak snare` so existe quando `--minimum-snare-velocity` esta
ativo.

Se a flag nao estiver ativa:

- nao existe filtro de weak snare

Se a flag estiver ativa:

- duas caixas do mesmo pitch dentro de `src_tpb // 8` podem marcar a primeira
  como fraca
- esse descarte continua subordinado a logica de flam acima

### 8.5 Note-on com velocity zero

`note_on` com `velocity == 0` sempre e ignorado. Isso evita confundir note-off
codado como note-on com hit real.

## 9. Escrita do `PART DRUMS`

O writer faz o seguinte:

- converte cada evento mapeado em pitch `96 + lane`
- escreve `note_on` e `note_off` com duracao de `1` tick
- cria markers `110`, `111`, `112` para todos os Y/B/G que sao toms
- os tom markers duram `target_tpb // 8`
- usa o `ticks_per_beat` da referencia
- constroi o MIDI final a partir da referencia, preservando as tracks dela
- substitui um `PART DRUMS` existente ou adiciona um novo se nao houver

O track gerado sempre comeca com:

- `track_name = PART DRUMS`
- `text = [mix 0 drums0]`

## 10. Scripts especificos por musica

### 10.1 Bubbles

`_analysis/postprocess_bubbles_songsterr.py` roda automaticamente quando o path
de entrada ou saida contem `system of a down - bubbles`.

Ele faz duas coisas:

1. troca blue cymbal <-> green cymbal no output
2. procura no source o padrao de hats:

```text
46, 42, 42, 46
```

e transforma o output correspondente em:

```text
Y, (drop), Y, B
```

Esse postprocess usa o mesmo `build_measure_marker_tick_mapper()` do pipeline
principal para localizar os ticks corretos no output.

Observacao importante:

- apesar do script existir e rodar automaticamente, `Bubbles` ainda nao deve ser
  tratada como "concluida"

### 10.2 Soldier Side

Dois caminhos existem para `Soldier Side`.

1. **Patch manual do source**

Arquivo:

- `_analysis/fix_soldier_side_songsterr_mid.py`

Uso tipico:

```bash
python3 _analysis/fix_soldier_side_songsterr_mid.py "<mid_path>" \
  --original-mid "<backup_original.mid>"
```

Ele:

- alterna o padrao crash+kick do source
- remove `closed hh` quando coincide com `snare + closed hh`
- converte quase todos os `closed hh` para ride
- preserva clusters rapidos de hats fechados

Esse script **nao** roda automaticamente no importer.

2. **Postprocess automatico do output**

Arquivo:

- `_analysis/postprocess_soldier_side_songsterr.py`

Ele roda automaticamente quando o path contem
`system of a down - soldier side`.

Regras atuais:

- secao de ride de `62976` a `76992`
- yellow accents apenas nos ticks:
  - `63744`
  - `66816`
  - `69888`
- garante ride blue adicional em `69504`

## 11. Casos reais que definiram a baseline

### Lonely Day

Licao permanente:

- a mesma musica pode ser escrita com grids ritmicos diferentes entre Songsterr
  e CH
- por isso o pipeline precisa confiar em anchors musicais, nao em BPM cru

### Sugar

Licao permanente:

- nunca corte fisicamente o source MIDI para "arrumar o primeiro compasso"
- isso desloca os `MEASURE_n` e quebra o sync
- para remover count-in ou hits iniciais, use `--drop-before-src-beat`

Tambem foi o caso que justificou o pareamento adaptativo `1x -> 2x`.

### Soil

Validou:

- alternancia real de `4/4` e `7/8`
- necessidade de interpretar `768` como "pular compassos + residuo"

### Question!

Validou:

- alternancia real de `9/8`, `5/4`, `3/4` e `4/4`
- mesma leitura correta do offset de `768`
- correcao global de flam de snare
- acoplamento entre weak snare e `--minimum-snare-velocity`
- `Hand Clap` ignorado globalmente

## 12. Status pratico das musicas

Musicas que hoje servem como referencia de robustez do algoritmo:

- `Sugar` -> stress test do pareamento `1x -> 2x`
- `Soil` -> stress test de `4/4 <-> 7/8`
- `Question!` -> stress test de `9/8`, `5/4`, `3/4`, `4/4`

Status importante para nao assumir errado:

- `Bubbles` -> tem automacao especifica, mas ainda precisa ser revisitada
- `A.D.D.` -> explicitamente marcada pelo usuario como precisando revisitacao
- `Sugar` -> o usuario ja editou trechos manualmente em certas iteracoes; evitar
  sobrescrever sem pedir

## 13. Ferramentas de debug que valem a pena

### 13.1 `generate_measure_debug_songsterr.py`

Esse script cria um MIDI de debug onde:

- cada compasso do source vira um bloco fixo de `4/4`
- existe um gap visual entre compassos
- os markers mostram `MEASURE_n`, tick inicial, tick final e tamanho original

Uso:

```bash
python3 _analysis/generate_measure_debug_songsterr.py "<src.mid>" "<out.mid>" \
  --drop-before-src-beat 0 \
  --dedup-beats 0.0625
```

Ele e util para inspecionar:

- quantas notas realmente existem em cada compasso do source
- se um problema e de mapeamento ou de warp

### 13.2 Inspecao direta via Python

Quando uma musica estranha aparecer:

1. inspecione `time_signature` e `set_tempo` do source
2. compare `MEASURE_n` do source com `measure_start_ticks(src_mid)`
3. compare `measure_start_ticks(ref_mid)` com o log do importer

Se os `MEASURE_n` baterem com os inicios de compasso reais do source, o source
esta estruturalmente bom.

## 14. Workflow operacional

### 14.1 Sequencia de comandos

Comandos dependentes devem rodar sequencialmente.

Ja houve leitura de arquivo stale quando geracao e passos seguintes ocorreram em
paralelo. Para esse repo:

- gere
- espere terminar
- sincronize

### 14.2 Regra de trabalho atual

Depois de qualquer alteracao em codigo **ou documentacao**, o workflow esperado
e:

1. regenerar a musica ativa
2. rodar `./sync_to_whisky.sh`

A musica mais recente usada como baseline de trabalho foi `Question!`.

### 14.3 `sync_to_whisky.sh`

Esse script:

- copia oficiais Harmonix para `SOAD-oficial`
- copia os resultados gerados para `SOAD-gerado`
- copia customs para `SOAD-custom`
- converte `.opus` para `.ogg` com cache em `_cache_ogg`
- cria copias timestampadas como:
  - `notes.songsterr-<dd-mm-hh-mm>.mid`
  - `notes.gen-<dd-mm-hh-mm>.mid`

No Moonscraper via Whisky, os caminhos importantes sao:

- `SOAD-oficial/<musica>/notes.mid`
- `SOAD-gerado/<musica>/notes.mid`
- `SOAD-custom/<musica>/notes.chart`

## 15. Regras de continuidade para a proxima LLM

1. Leia este arquivo primeiro.
2. Preserve o pipeline atual como baseline.
3. Antes de criar helper novo, procure em `_analysis/` se ja existe modulo para
   isso.
4. Se mexer em sync:
   - teste pelo menos em `Sugar`, `Soil` e `Question!`
5. Se mexer em mapeamento/flam/snare:
   - teste pelo menos na musica ativa
   - regenere e sincronize no final
6. Nao silencie erros estruturais:
   - sem referencia
   - sem `MEASURE_n`
   - sem track de bateria valida
7. Atualize este arquivo, nao espalhe uma nova "fonte da verdade" em outro `.md`.
