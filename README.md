# Songsterr Drum Import

> Este arquivo é a fonte canônica de handoff para o import de bateria do Songsterr.
> projeto está descrito aqui e deve prevalecer sobre qualquer documento antigo.

## 1. Objetivo

Gerar uma `PART DRUMS` Expert para Clone Hero a partir de um MIDI do Songsterr,
alinhando a bateria ao tempo real da chart de referência.

Cenário real de produção:

- a pasta da música (ver seção 2) já tem `notes.chart` ou `notes.mid` sincronizado ao audio
- normalmente existe `PART GUITAR`, mas não `PART DRUMS`
- o Songsterr fornece o MIDI fonte com a bateria em GM no canal 9
- o resultado final deve ser salvo como `notes.songsterr.mid`

A verdade temporal final é sempre a chart de referência. O MIDI do Songsterr
só fornece a estrutura musical e os anchors de compasso.

## 2. Estrutura atual

### 2.1 Onde ficam `notes.mid` e `notes.chart` no repositório

- **Packs Harmonix (oficiais)**: pastas na **raiz do repo** com o padrão
  `System of a Down - <titulo> (Harmonix)/`. Cada música é uma pasta; dentro
  ficam `notes.mid` e, se existir, `notes.chart`, mais `notes.songsterr.mid` /
  `notes.songsterr.mid` (e por vezes `notes.songsterr-<dd-mm-hh-mm>.mid` como
  backup), `song.ini`, `album.jpg`, audio, etc. O `sync_songs.sh` (ver seção 15)
  toma `notes.songsterr.mid` e publica em `Songs/…/notes.mid`.

- **Jogo (Clone Hero)**: `Songs/<nome da pasta>/` — destino alvo do sync. Cada
  música é uma subpasta com `notes.mid` (a chart servida no jogo: cópia de
  `notes.songsterr.mid` na origem), `song.ini`, audio, etc. O sync não traz
  `*.mid` / `*.chart` extra da origem, só o `notes.mid` acima.

- **Charts da comunidade (custom)**: `custom/<nome-da-pasta>/`, com a mesma
  ideia de arquivos por música (`notes.chart` e/ou `notes.mid` conforme o caso).

- **Não** usamos mais o layout antigo `songs/harmonix/…` na raiz deste repo;
  alguns blocos `if __name__ == "__main__"` em `src/` ainda podem apontar para
  esse caminho só para debug local — ajuste o `base` se for correr isso aí.

### 2.2 Organização do `src`

O `src` está organizado por responsabilidade:

- `src/songsterr_parsing`
  - importer principal do Songsterr
  - pipeline e helpers específicos do Songsterr
- `src/chart_generation`
  - parsing de chart e MIDI
  - escrita do `notes.mid` final
  - `chart_sync/` com análises de alinhamento e sync
- `src/difficulty_generation`
  - geração de dificuldades faltantes
  - `difficulty_analysis/` com validações e análises auxiliares

## 3. Arquivos canônicos

Pipeline principal:

- `src/chart_generation/parse_chart.py`
- `src/chart_generation/parse_drums.py`
- `src/songsterr_parsing/import_songsterr.py`
- `src/songsterr_parsing/songsterr_import/context.py`
- `src/songsterr_parsing/songsterr_import/pipeline.py`
- `src/songsterr_parsing/songsterr_import/measure_marker_sync.py`
- `src/songsterr_parsing/songsterr_import/source.py`
- `src/songsterr_parsing/songsterr_import/mapping.py`
- `src/songsterr_parsing/songsterr_import/writer.py`
- `src/songsterr_parsing/songsterr_import/constants.py`

Scripts e ferramentas (sync e entrega):
- `sync_songs.sh` (ambiente com `bash`) e `sync_songs.ps1` (Windows) — mesma regra: publicar `notes.songsterr.mid` em `Songs/.../notes.mid` e copiar o resto da origem
- `src/songsterr_parsing/download_songsterr_midi.py` — baixar MIDI a partir de URL (requer arquivo de cookies de sessão; export via API de usuário autenticado, tipicamente Songsterr Plus)
- `tools/songsterr_workflow.ps1` — encadear *download* + *import* + *sync* no console (não invoca a aplicação WPF)
- `tools/SongsterrImport.sln` — UI WPF (`SongsterrImport.Desktop`): escolhe pasta em `Songs/`, login Songsterr no WebView2, grava cookies, lança os mesmos `py` e `sync_songs.ps1` com log
  - Na **raiz do repo**: `Iniciar-Songsterr-Import.bat` (duplo clique: compila e abre; precisa de .NET 8 SDK) e `Criar-Atalho-No-Desktop.bat` (cria `Songsterr Import.lnk` na área de trabalho apontando para o `exe` em `bin\Debug\net8.0-windows\`)

`requirements.txt` na raiz: `mido`, `requests`. Variável de ambiente de trabalho: `PYTHONPATH=src;src/chart_generation` (Windows usa `;` no caminho).

Redução e geração de dificuldades:

- `src/difficulty_generation/reducer.py`
- `src/difficulty_generation/reducer_drums.py`
- `src/chart_generation/midi_writer.py`

Análises e debug:

- `src/chart_generation/chart_sync/align.py`
- `src/chart_generation/chart_sync/align_drums.py`
- `src/difficulty_generation/difficulty_analysis/validate.py`
- `src/difficulty_generation/difficulty_analysis/deep_dive.py`
- `src/difficulty_generation/difficulty_analysis/finer.py`

## 4. Comando de produção

Uso básico:

```bash
python3 src/songsterr_parsing/import_songsterr.py "<songsterr.mid>" "<out.mid>"
```

Flags ativas hoje:

```bash
python3 src/songsterr_parsing/import_songsterr.py "<songsterr.mid>" "<out.mid>" \
  --ref-path "<notes.chart|notes.mid>" \
  --initial-offset-ticks 768 \
  --dedup-beats 0.0625 \
  --filter-weak-snares
```

Semântica atual das flags:

- `--ref-path`: override explicito da chart de referência
- `--initial-offset-ticks`: offset global aplicado depois do mapeamento por compassos
- `--dedup-beats`: janela em beats: se `convert flams` estiver ativo, pares muito
  perto na mesma lane sao tratados como flam (ver secao 9)
- `--filter-weak-snares` (opcional): remove caixas com velocity abaixo do padrao
  (ghosts). Sem esta flag, todas as caixas (incluindo soft) entram
- `--no-convert-flams` (opcional): nao aplica a logica de flam/dedup por
  proximidade; todos os hits source sao mapeados sem R+Y nem colapso de pares

Auto-detecção de referência:

- `notes.chart`
- `notes.mid`

O importer procura esses arquivos no diretorio do `src_mid`, do `out_mid` e do
`--ref-path` quando existe (tipicamente a **mesma pasta** da música ém
`System of a Down - … (Harmonix)/` ou em `custom/…/`). Se não achar referência
válida, falha com erro.

### 4.1 Baixar o MIDI do Songsterr (URL)

O export no site exige **sessão** (conta; exportação MIDI costuma exigir **Plus**). O script `download_songsterr_midi.py` usa `POST https://www.songsterr.com/api/edits/download` com o corpo JSON (revision, song, parts, lyrics, midi) e os **cookies** gravados pela app (WebView2) em `%LocalAppData%\SongsterrImport\songsterr_cookies.json` (array JSON de cookies por domínio). Sem cookies válidos, o passo de download falha com 401/403 e mensagem explícita.

Exemplo (raiz do repo, PowerShell, `PYTHONPATH=src;src\chart_generation`):

```powershell
py -3 src/songsterr_parsing/download_songsterr_midi.py "https://www.songsterr.com/a/wsa/...-s21961" "Songs/...\songsterr_in.mid" --cookie-file "$env:LOCALAPPDATA\SongsterrImport\songsterr_cookies.json"
```

A sequencia de terminal documentada (sem abrir a GUI) esta em `tools/songsterr_workflow.ps1`.

## 5. Modelo de sync em produção

O pipeline ativo usa apenas `MEASURE_n`.

### 4.1 Fonte dos anchors

- `_source_measure_marker_ticks()` lê os markers `MEASURE_n` da track de bateria
  escolhida no Songsterr
- `measure_start_ticks()` calcula os inícios de compasso da referência a partir
  dos `time_signature` reais do conductor

Isso suporta naturalmente músicas com mudança de formula de compasso:

- `4/4`
- `7/8`
- `9/8`
- `5/4`
- `3/4`
- `6/8`

Se o Songsterr não tiver markers `MEASURE_n` suficientes na track de bateria, o
pipeline deve falhar. Não existe fallback silencioso.

### 4.2 Warp por compasso

`_build_adaptive_measure_anchors()` compara a duração real, em segundos, de:

- 1 compasso do source
- 1 compasso da referência
- 2 compassos consecutivos da referência

Se 2 compassos da referência casarem melhor com 1 compasso do source por uma
margem real de pelo menos `0.05s`, o importer usa um pareamento `1x -> 2x`.
Nesse caso ele cria um anchor sintetico no meio do compasso do source para
interpolar a metade correspondente.

Esse comportamento existe para casos como o interludio de `Sugar`.

### 4.3 Offset inicial

`DEFAULT_INITIAL_OFFSET_TICKS = 768`.

O offset inicial não e mais somado cegamente a todos os ticks da referência.
Ele e interpretado como:

- quantos compassos inteiros da chart devem ser pulados
- mais um residuo fino em ticks

Charts que tem um compasso extra no comeco pois é assim que é o formato esperado no Clone Hero, por isso que usamos 768, que é exatamente um compasso.

Casos reais que validaram essa regra:

- `Soil`: alternância `4/4` e `7/8`
- `Question!`: alternância `9/8`, `5/4`, `3/4` e `4/4`

Nos logs do importer isso aparece como:

- `offset manual=+768 ticks (pula 1 compassos da chart)`

### 4.4 Interpretacao correta do tempo

Não confie em BPM nominal puro.

A mesma música pode ser escrita com:

- formulas de compasso diferentes
- BPMs aparentes diferentes
- mesma duração musical real

O que importa e:

- os anchors musicais do source
- o mapa temporal final da chart de referência

## 6. Selecao da track de bateria

`select_source_drum_track()` não escolhe a primeira track do canal 9.

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

## 7. Mapeamento atual de notas GM -> CH

### 6.1 Notas mapeadas diretamente

- `35`, `36` -> kick
- `37`, `38`, `40` -> snare
- `42` -> yellow cymbal
- `46` -> yellow cymbal por padrão
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

Se a música não usa toms altos (`48` ou `50`), o kit baixo é reescalado assim:

- maior pitch presente do grupo baixo -> yellow
- segundo maior -> blue
- restantes -> green

2. **Viradas de low tom**

Se uma corrida contem apenas low toms e não vem de uma sequencia com upper tom
antes, o maior low tom da corrida vira blue e o menor vira green. Isso deixa
fills `floor -> very low` mais legiveis no CH.

## 8. Regras atuais de hihat / prato

### 7.1 Open hihat

`46` e yellow por padrão.

Ele só vira blue quando:

- esta entre dois `42`
- os gaps anterior e posterior sao equilibrados
- e não faz parte de uma alternância mais longa de open hats

Isso modela o caso "open isolado entre closed hats".

### 7.2 Closed hihat que deve sumir

O closed `42` e descartado quando:

- aparece entre dois `46`
- os gaps anterior e posterior sao equilibrados

Na pratica, uma sequencia como:

- `46, 42, 46`

vira:

- `Y, (drop), Y`

Numa alternância maior como:

- `46, 42, 46, 42`

o open continua yellow e o closed do meio some. Isso evita transformar esse
padrão em uma parede azul.

## 9. Flam, dedup e filtros de snare

### 8.1 Janela de dedup

`--dedup-beats` vale `1/16 beat` por padrão. Só aplica se a lógica de
conversão de flams estiver ativa; com `--no-convert-flams`, a janela e ignorada
(isso equivale, no código, a não fundir pares no mesmo corredor).

Para hits na mesma lane dentro dessa janela (com conversão de flam ligada):

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

### 8.3 Filtro de velocity de caixa (ghost / soft)

`--filter-weak-snares` e opcional.

Comportamento atual:

- se **não** passar a flag, todo hit com `velocity > 0` entra (inclui notas
  muito suaves)
- com **`--filter-weak-snares`**, aplica-se o corte `DEFAULT_MINIMUM_SNARE_VELOCITY` (75)
  apenas a snares
- outras peças nunca usam esse corte

### 8.4 Weak snare

O descarte de `weak snare` só existe quando `--filter-weak-snares` está
ativo.

Se a flag não estiver ativa:

- não existe filtro de weak snare

Se a flag estiver ativa:

- duas caixas do mesmo pitch dentro de `src_tpb // 8` podem marcar a primeira
  como fraca
- esse descarte continua subordinado a logica de flam acima

### 8.5 Note-on com velocity zero

`note_on` com `velocity == 0` sempre e ignorado. Isso evita confundir note-off
codado como note-on com hit real.

## 10. Escrita do `PART DRUMS`

O writer faz o seguinte:

- converte cada evento mapeado em pitch `96 + lane`
- escreve `note_on` e `note_off` com duração de `1` tick
- cria markers `110`, `111`, `112` para todos os Y/B/G que sao toms
- os tom markers duram `target_tpb // 8`
- usa o `ticks_per_beat` da referência
- constrói o MIDI final a partir da referência, preservando as tracks dela
- substitui um `PART DRUMS` existente ou adiciona um novo se não houver

O track gerado sempre comeca com:

- `track_name = PART DRUMS`
- `text = [mix 0 drums0]`

## 11. Pós-processos por música (histórico)

Houve, no passado, scripts ad hoc (`postprocess_bubbles_songsterr`, `postprocess_soldier_side_songsterr`, `fix_soldier_side_songsterr_mid`, etc.) que **deixaram de fazer** parte do repositório. O `import_songsterr` atual não aplica pós-processamento por música. Casos de borderline (Bubbles, Soldier Side, A.D.D.) exigem revisão manual se necessário.

## 12. Casos reais que definiram a baseline

### Lonely Day

Licao permanente:

- a mesma música pode ser escrita com grids rítmicos diferentes entre Songsterr
  e CH
- por isso o pipeline precisa confiar em anchors musicais, não em BPM cru

### Sugar

Licao permanente:

- nunca corte fisicamente o source MIDI para "arrumar o primeiro compasso"
- isso desloca os `MEASURE_n` e quebra o sync
- count-in no source: resolva na fonte (chart/referencia ou edicao fora do
  `import_songsterr`); a flag de drop por beat foi removida do import

Tambem foi o caso que justificou o pareamento adaptativo `1x -> 2x`.

### Soil

Validou:

- alternância real de `4/4` e `7/8`
- necessidade de interpretar `768` como "pular compassos + residuo"

### Question!

Validou:

- alternância real de `9/8`, `5/4`, `3/4` e `4/4`
- mesma leitura correta do offset de `768`
- correcao global de flam de snare
- acoplamento entre weak snare e `--filter-weak-snares`
- `Hand Clap` ignorado globalmente

## 13. Status prático das musicas

Músicas que hoje servem como referência de robustez do algoritmo:

- `Sugar` -> stress test do pareamento `1x -> 2x`
- `Soil` -> stress test de `4/4 <-> 7/8`
- `Question!` -> stress test de `9/8`, `5/4`, `3/4`, `4/4`

Status importante para não assumir errado:

- `Bubbles` -> ainda e tratada com cuidado (nenhum pós-processamento automatico hoje)
- `A.D.D.` -> explicitamente marcada pelo usuario como precisando revisitacao
- `Sugar` -> o usuário já editou trechos manualmente em certas iteraçoes; evitar
  sobrescrever sem pedir

## 14. Ferramentas de debug

O antigo `generate_measure_debug_songsterr.py` já não esta no repositório. Para depurar, use `src/chart_generation/chart_sync/align*.py`, `difficulty_analysis/`, e inspeção direta:

### 14.1 Inspeção direta via Python

Quando uma música éstranha aparecer:

1. inspecione `time_signature` e `set_tempo` do source
2. compare `MEASURE_n` do source com `measure_start_ticks(src_mid)`
3. compare `measure_start_ticks(ref_mid)` com o log do importer

Se os `MEASURE_n` baterem com os inícios de compasso reais do source, o source
esta estruturalmente bom.

## 15. Workflow operacional

### 14.1 Sequencia de comandos

Comandos dependentes devem rodar sequencialmente.

Já houve leitura de arquivo stale quando geração e passos seguintes ocorreram em
paralelo. Para esse repo:

- gere
- espere terminar
- sincronize

### 14.2 Regra de trabalho atual

Depois de qualquer alteracao em codigo **ou documentacao**, o workflow esperado
e:

1. regenerar a música ativa
2. rodar o sync (ver abaixo)

A música mais recente usada como baseline de trabalho foi `Question!`.

### 14.3 `sync_songs.sh` e `sync_songs.ps1`

O script **exige dois argumentos**: pasta de **origem** (ex.:
`original/custom/System of a Down - Soil (Wagsii)/` ou a pasta de trabalho na
raiz) e o **destino sob** `Songs/` (pasta a criar ou reutilizar, ex.:
`System of a Down - Soil`; também se pode passar `Songs/…` e o path é
normalizado).

A partir da raiz do repositório (bash):

```bash
./sync_songs.sh "original/custom/System of a Down - Soil (Wagsii)" "System of a Down - Soil"
```

No **Windows** (mesma semântica):

```powershell
.\sync_songs.ps1 "C:\...\pasta-origem-com-notes.songsterr.mid" "System of a Down - Soil"
```

Comportamento (ambas as variantes):

- Exige `notes.songsterr.mid` na origem e grava `Songs/<pasta>/notes.mid` a
  partir dele.
- Copia o **restante** da origem para o destino, **excluindo** todos os
  `*.mid` e `*.chart` (fica só o `notes.mid` escrito acima).
- Cria a pasta de destino sob `Songs/` se ainda não existir.

### 14.4 Ajuste de pastas: nome igual ao de `original/custom/`

Se em `Songs/` a pasta tiver o nome “curto” (sem ` (autor)`) e em
`original/custom/` existir a pasta com o sufixo do chart, use:

```powershell
.\tools\align_songs_folders_to_custom.ps1 -RepoRoot $PWD
```

Renomeia `Songs\Nome Curto` para `Songs\Nome Curto (Wagsii)` (exemplo) quando
há correspondência unívoca. Se duas pastas de custom compartilharem o mesmo
nome após retirar o sufixo, o script avisa e não mexe em nada.

## 16. Regras de continuidade para a próxima LLM

1. Leia este arquivo primeiro.
2. Preserve o pipeline atual como baseline.
3. Antes de criar helper novo, procure em `src/` se já existe módulo para
   isso.
4. Se mexer em sync:
   - teste pelo menos em `Sugar`, `Soil` e `Question!`
5. Se mexer em mapeamento/flam/snare:
   - teste pelo menos na música ativa
   - regenere e sincronize no final
6. Não silencie erros estruturais:
   - sem referência
   - sem `MEASURE_n`
   - sem track de bateria válida
7. Atualize este arquivo, não espalhe uma nova "fonte da verdade" em outro `.md`.
