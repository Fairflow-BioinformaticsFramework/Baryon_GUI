# BaryonRunner

Minimal GUI per:
- caricare un file `.bala`
- generare automaticamente la form di file, directory e parametri
- lanciare direttamente il container descritto dal `.bala`
- scaricare frontend generati (`Nextflow`, `Streamflow`, `Galaxy`, `Python`, `Bash`, `R`)

## Avvio

Windows:
```bat
run.bat
```

Linux/macOS:
```bash
chmod +x run.sh
./run.sh
```

GUI: http://localhost:8082

## Stato attuale

Questo è un prototipo funzionante. Fa queste cose:
- parse di `[research]`, `[run]`, `[file]`, `[directory]`, `[parameter]`
- tollera anche il typo `[directoy]`
- crea una form dinamica
- permette di cambiare i parametri invece di usare solo i default
- esegue il docker definito in `[run]`
- genera zip con frontend esportati

## Nota pratica

Per l'esecuzione diretta, il runner usa convenzioni semplici:
- i file con `flag=r` vengono montati come sola lettura sotto `/baryon/input/...`
- i file con `flag=c` vengono copiati nella `workDir` se presente
- ogni `[directory]` viene montata come `/baryon/<name>`

Quindi è ottimo per testare subito la UX, ma potresti voler raffinare in seguito la semantica precisa dei mount/path.
