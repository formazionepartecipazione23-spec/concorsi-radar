from .inpa_portale import InpaPortale
from .inpa_wp import InpaWordPress
from .gazzetta import GazzettaConcorsi

REGISTRY = {"inpa_portale": InpaPortale, "inpa_wp": InpaWordPress, "gazzetta": GazzettaConcorsi}
