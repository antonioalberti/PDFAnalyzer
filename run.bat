@echo off
for /l %%i in (0,1,42) do (
    echo Processando arquivo %%i.PDF
    python main.py C:\Users\alberti\Documents\Artigos\%%i.PDF > C:\Users\alberti\Documents\Artigos\%%i.txt
)
echo Todos os arquivos processados.
