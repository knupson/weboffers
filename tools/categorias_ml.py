"""Categoría del sitio desde el dominio de la ficha de ML (domain_id).

Una sola fuente para crecer_desde_ml, corregir_categorias y el validador (match_candidates, 11/11).
"""


# 05/11: categoría del sitio desde el dominio de la ficha de ML (domain_id). Adivinarla por palabras del título de
# Amazon puso un celular en «Cámaras» (por su cámara) y un TV Box en «Almacenamiento» (por sus 32 GB).
DOMINIOS = (
    ("CELLPHONE", "Celulares"), ("SMARTPHONE", "Celulares"),
    ("TABLET", "Tablets y lectores"), ("EBOOK_READER", "Tablets y lectores"), ("E_BOOK", "Tablets y lectores"),
    ("SMARTWATCH", "Relojes"), ("FITNESS_TRACKER", "Relojes"), ("WATCH", "Relojes"),
    ("MONITOR", "Monitores"), ("MINI_PC", "Mini PCs"), ("ROUTER", "Redes"), ("NETWORK", "Redes"), ("MESH", "Redes"),
    ("HARD_DRIVE", "Almacenamiento"), ("SOLID_STATE", "Almacenamiento"), ("SSD", "Almacenamiento"),
    ("MEMORY_CARD", "Almacenamiento"), ("USB_FLASH", "Almacenamiento"), ("PEN_DRIVE", "Almacenamiento"),
    ("KEYBOARD", "Periféricos"), ("MOUSE", "Periféricos"), ("MICE", "Periféricos"), ("WEBCAM", "Periféricos"),
    ("GAME_CONSOLE", "Gaming"), ("VIDEO_GAME", "Gaming"), ("GAMEPAD", "Gaming"), ("JOYSTICK", "Gaming"),
    ("CPU", "Componentes"), ("PROCESSOR", "Componentes"), ("GRAPHICS_CARD", "Componentes"), ("MOTHERBOARD", "Componentes"),
    ("RAM_MEMOR", "Componentes"), ("POWER_SUPPL", "Componentes"), ("COMPUTER_COOLER", "Componentes"),
    ("DRONE", "Cámaras"), ("CAMERA", "Cámaras"), ("LENS", "Cámaras"), ("CAMCORDER", "Cámaras"),
    ("POWER_BANK", "Carga y energía"), ("CHARGER", "Carga y energía"),
    ("PRINTER", "Oficina"),
    ("SPEAKER", "Audio y video"), ("HEADPHONE", "Audio y video"), ("EARPHONE", "Audio y video"), ("SOUNDBAR", "Audio y video"),
    ("STREAMING", "Audio y video"), ("TV_BOX", "Audio y video"), ("TELEVISION", "Audio y video"), ("PROJECTOR", "Audio y video"),
    ("DJ_", "Audio y video"), ("MICROPHONE", "Audio y video"), ("AUDIO_INTERFACE", "Audio y video"), ("SMART_SPEAKER", "Audio y video"),
    ("VOICE_RECORDER", "Audio y video"), ("TURNTABLE", "Audio y video"),
)


def categoria_ml(domain_id):
    dominio = (domain_id or "").upper()
    return next((cat for clave, cat in DOMINIOS if clave in dominio), "")


# 11/11: el validador NO usa la búsqueda por subcadena de arriba (revisor: «BABY_MONITORS» → Monitores, «STOPWATCHES»
# → Relojes, «FOOD_PROCESSORS» → Componentes, «CAMERA_BACKPACKS» → Cámaras). Sólo dominios exactos, cada uno leído
# en una ficha real de ML. Para sumar uno: leer /products/<id> de un par real y agregarlo con su ejemplo.
DOMINIOS_EXACTOS = {
    "MLA-WRISTWATCHES": "Relojes",                                  # Bulova 96B469, Casio DW-H5600 (MLA68598714)
    "MLA-HARD_DRIVES_AND_SSDS": "Almacenamiento",                   # Samsung 9100 PRO 2TB (MLA58973109)
    "MLA-DESKTOP_COMPUTER_POWER_SUPPLIES": "Componentes",           # CORSAIR RM1000x (MLA64603822)
    "MLA-COMPUTER_MONITORS": "Monitores",                           # ARZOPA Z1FC (MLA46016089)
}


def categoria_ml_exacta(domain_id):
    return DOMINIOS_EXACTOS.get((domain_id or "").upper(), "")
