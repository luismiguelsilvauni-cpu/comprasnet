@echo off
echo ============================================
echo   Iniciar SQL Server Express
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERRO: Execute este ficheiro como Administrador.
    echo Clique com o botao direito e escolha "Executar como administrador"
    pause
    exit
)

sc query "MSSQL$SQLEXPRESS" | find "RUNNING" >nul 2>&1
if not errorlevel 1 (
    echo SQL Server ja esta a correr.
    pause
    exit
)

echo A iniciar SQL Server Express...
net start "MSSQL$SQLEXPRESS"

if errorlevel 1 (
    echo.
    echo ERRO: Nao foi possivel iniciar o SQL Server.
) else (
    echo.
    echo SQL Server iniciado com sucesso!
)

pause
