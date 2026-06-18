# mortalidad-gt-bi
## Correr las ingestas de la primera fase fuente por fuente activar el venv desde la raiz con
source venv/bin/activate
## ir a la carpeta ingesta-fase1/:
python main.py --fuente ine
python main.py --fuente world_mortality
python main.py --fuente centroamerica
python main.py --fuente mspas_mec
python main.py --fuente mspas_covid
python main.py --fuente oms


## Para correr las transformaciones debes ir a la carpeta transformacion-fase2/transformation/ y correr: