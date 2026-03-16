"""Semantic track profile generation from genre/tag heuristics."""

import logging
from typing import Any

from app.database_pg import get_cursor, get_connection

logger = logging.getLogger(__name__)

# Energy keywords (0-1 scale)
ENERGY_KEYWORDS = {
    # High energy (0.8-1.0)
    'death metal': 0.95,
    'thrash metal': 0.95,
    'grindcore': 1.0,
    'powerviolence': 1.0,
    'hardcore': 0.9,
    'metalcore': 0.85,
    'deathcore': 0.9,
    'industrial': 0.8,
    'techno': 0.85,
    'gabber': 1.0,
    'speedcore': 1.0,
    'drum and bass': 0.85,
    'punk': 0.85,
    'power metal': 0.85,
    'speed metal': 0.9,
    'crossover': 0.85,
    'crust punk': 0.9,
    'd-beat': 0.92,
    'street punk': 0.85,
    'oi': 0.82,
    'skate punk': 0.85,
    'brutal death metal': 0.98,
    'technical death metal': 0.92,
    'war metal': 0.95,
    'bestial black metal': 0.95,
    'black thrash': 0.88,
    'noise rock': 0.8,
    'math rock': 0.7,
    'mathcore': 0.88,

    'crossover thrash': 0.88,
    'bay area thrash': 0.91,
    'teutonic thrash': 0.91,
    'blackened thrash': 0.89,
    'technical thrash': 0.90,
    'proto-thrash': 0.82,
    'death thrash': 0.92,

    # Medium-high energy (0.6-0.8)
    'black metal': 0.75,
    'heavy metal': 0.7,
    'rock': 0.6,
    'hard rock': 0.7,
    'alternative rock': 0.6,
    'progressive metal': 0.65,
    'melodic death metal': 0.8,
    'trance': 0.75,
    'house': 0.7,
    'electronic': 0.6,
    'synthwave': 0.65,
    'ebm': 0.7,
    'industrial metal': 0.78,
    'industrial rock': 0.68,
    'aggrotech': 0.75,
    'electro-industrial': 0.72,
    'power electronics': 0.8,
    'death industrial': 0.65,
    'garage rock': 0.7,
    'garage punk': 0.75,
    'psychobilly': 0.75,
    'horror punk': 0.72,
    'gothic metal': 0.6,
    'symphonic black metal': 0.72,
    'atmospheric black metal': 0.6,
    'blackgaze': 0.55,
    'post-black metal': 0.58,
    'melodic black metal': 0.7,
    'viking metal': 0.65,
    'pagan metal': 0.65,
    'folk metal': 0.65,
    'progressive death metal': 0.7,
    'old school death metal': 0.88,
    'swedish death metal': 0.88,
    'florida death metal': 0.9,
    'hip-hop': 0.65,
    'rap': 0.65,
    'trap': 0.7,
    'grime': 0.75,
    'dancehall': 0.7,
    'reggaeton': 0.7,
    'ska': 0.65,
    'ska punk': 0.75,
    'rockabilly': 0.65,
    'surf rock': 0.6,

    # Medium energy (0.4-0.6)
    'progressive rock': 0.5,
    'post-rock': 0.45,
    'post-metal': 0.5,
    'shoegaze': 0.45,
    'indie': 0.5,
    'alternative': 0.5,
    'new wave': 0.55,
    'synth-pop': 0.55,
    'pop': 0.55,
    'post-punk': 0.55,
    'coldwave': 0.4,
    'cold wave': 0.4,
    'minimal wave': 0.4,
    'deathrock': 0.55,
    'gothic rock': 0.5,
    'batcave': 0.5,
    'ethereal wave': 0.35,
    'ethereal': 0.35,
    'dream pop': 0.4,
    'indie rock': 0.55,
    'indie pop': 0.5,
    'britpop': 0.55,
    'krautrock': 0.5,
    'kosmische': 0.4,
    'space rock': 0.5,
    'psychedelic rock': 0.5,
    'acid rock': 0.55,
    'stoner rock': 0.5,
    'desert rock': 0.5,
    'blues rock': 0.55,
    'blues': 0.45,
    'funk': 0.65,
    'soul': 0.5,
    'r&b': 0.5,
    'reggae': 0.5,
    'dub': 0.45,
    'latin': 0.55,
    'flamenco': 0.5,
    'bossa nova': 0.35,
    'jazz fusion': 0.55,
    'jazz rock': 0.55,
    'no wave': 0.6,
    'witch house': 0.4,
    'vaporwave': 0.35,
    'chillwave': 0.35,
    'lo-fi': 0.4,
    'electropunk': 0.65,
    'electroclash': 0.6,

    # Low-medium energy (0.2-0.4)
    'doom metal': 0.35,
    'stoner': 0.4,
    'sludge': 0.45,
    'gothic': 0.35,
    'darkwave': 0.35,
    'trip-hop': 0.35,
    'downtempo': 0.3,
    'chillout': 0.25,
    'neofolk': 0.3,
    'dark folk': 0.3,
    'apocalyptic folk': 0.3,
    'martial industrial': 0.35,
    'military pop': 0.3,
    'ritual ambient': 0.2,
    'dungeon synth': 0.2,
    'stoner doom': 0.35,
    'epic doom': 0.3,
    'traditional doom': 0.3,
    'jazz': 0.4,
    'free jazz': 0.55,
    'bebop': 0.5,
    'swing': 0.5,
    'cool jazz': 0.35,
    'smooth jazz': 0.3,
    'lounge': 0.3,
    'easy listening': 0.25,
    'world music': 0.4,
    'afrobeat': 0.6,
    'highlife': 0.55,
    'country': 0.45,
    'americana': 0.4,
    'bluegrass': 0.5,
    'singer-songwriter': 0.35,

    # Low energy (0.0-0.2)
    'ambient': 0.15,
    'dark ambient': 0.1,
    'drone': 0.1,
    'funeral doom': 0.2,
    'folk': 0.3,
    'acoustic': 0.25,
    'classical': 0.3,
    'neoclassical': 0.25,
    'meditation': 0.05,
    'sleep': 0.05,
    'neoclassical darkwave': 0.2,
    'dark cabaret': 0.35,
    'chamber music': 0.2,
    'drone doom': 0.15,
    'isolationism': 0.1,
    'field recordings': 0.05,
    'musique concrète': 0.15,
    'glitch': 0.3,
    'microsound': 0.15,
    'lowercase': 0.05,
}

# Darkness keywords (0-1 scale, 1 = darkest)
DARKNESS_KEYWORDS = {
    # Very dark (0.8-1.0)
    'black metal': 0.95,
    'dark ambient': 1.0,
    'funeral doom': 0.95,
    'depressive': 1.0,
    'suicidal': 1.0,
    'doom metal': 0.85,
    'death metal': 0.8,
    'gothic': 0.8,
    'darkwave': 0.85,
    'industrial': 0.75,
    'noise': 0.8,
    'harsh noise': 0.9,
    'depressive black metal': 1.0,
    'dsbm': 1.0,
    'drone doom': 0.9,
    'death doom': 0.88,
    'ritual ambient': 0.92,
    'death industrial': 0.9,
    'power electronics': 0.85,
    'dungeon synth': 0.85,
    'coldwave': 0.8,
    'cold wave': 0.8,
    'deathrock': 0.82,
    'gothic rock': 0.75,
    'batcave': 0.78,
    'war metal': 0.9,
    'bestial black metal': 0.9,
    'black thrash': 0.82,
    'isolationism': 0.9,
    'witch house': 0.8,

    # Dark (0.6-0.8)
    'sludge': 0.7,
    'stoner': 0.6,
    'post-metal': 0.65,
    'drone': 0.7,
    'atmospheric black metal': 0.8,
    'blackgaze': 0.7,
    'deathcore': 0.7,
    'grindcore': 0.65,
    'neofolk': 0.7,
    'dark folk': 0.75,
    'apocalyptic folk': 0.78,
    'martial industrial': 0.72,
    'military pop': 0.65,
    'neoclassical darkwave': 0.78,
    'dark cabaret': 0.65,
    'minimal wave': 0.72,
    'ethereal wave': 0.6,
    'ethereal': 0.55,
    'post-punk': 0.6,
    'electro-industrial': 0.68,
    'aggrotech': 0.65,
    'industrial metal': 0.7,
    'industrial rock': 0.6,
    'epic doom': 0.78,
    'traditional doom': 0.78,
    'stoner doom': 0.72,
    'symphonic black metal': 0.75,
    'melodic black metal': 0.72,
    'post-black metal': 0.7,
    'old school death metal': 0.78,
    'swedish death metal': 0.75,
    'florida death metal': 0.78,
    'brutal death metal': 0.8,
    'technical death metal': 0.72,
    'progressive death metal': 0.65,
    'crust punk': 0.65,
    'd-beat': 0.62,
    'noise rock': 0.6,
    'no wave': 0.6,
    'horror punk': 0.68,
    'psychobilly': 0.55,

    'bay area thrash': 0.74,
    'teutonic thrash': 0.78,
    'blackened thrash': 0.88,
    'technical thrash': 0.70,
    'proto-thrash': 0.65,
    'death thrash': 0.85,
    'speed metal': 0.60,

    # Neutral-dark (0.4-0.6)
    'heavy metal': 0.5,
    'thrash metal': 0.72,
    'progressive metal': 0.5,
    'metalcore': 0.55,
    'hardcore': 0.5,
    'post-rock': 0.45,
    'shoegaze': 0.45,
    'trip-hop': 0.5,
    'ebm': 0.6,
    'dream pop': 0.4,
    'krautrock': 0.4,
    'kosmische': 0.4,
    'space rock': 0.45,
    'acid rock': 0.45,
    'garage rock': 0.4,
    'garage punk': 0.45,
    'blues': 0.45,
    'blues rock': 0.4,
    'gothic metal': 0.65,
    'viking metal': 0.55,
    'pagan metal': 0.55,
    'folk metal': 0.45,
    'melodic death metal': 0.65,
    'street punk': 0.45,
    'oi': 0.42,
    'vaporwave': 0.45,
    'lo-fi': 0.4,
    'hip-hop': 0.45,
    'rap': 0.45,
    'grime': 0.55,
    'free jazz': 0.5,
    'avant-garde': 0.5,
    'experimental': 0.45,
    'musique concrète': 0.55,

    # Neutral (0.3-0.5)
    'rock': 0.4,
    'alternative': 0.4,
    'electronic': 0.4,
    'techno': 0.45,
    'house': 0.35,
    'trance': 0.35,
    'progressive rock': 0.4,
    'psychedelic rock': 0.4,
    'indie rock': 0.35,
    'indie': 0.35,
    'britpop': 0.3,
    'stoner rock': 0.5,
    'desert rock': 0.5,
    'dub': 0.45,
    'reggae': 0.35,
    'jazz': 0.35,
    'bebop': 0.35,
    'cool jazz': 0.35,
    'jazz fusion': 0.35,
    'jazz rock': 0.35,
    'electroclash': 0.45,
    'electropunk': 0.45,
    'chillwave': 0.35,
    'glitch': 0.4,
    'world music': 0.3,
    'country': 0.3,
    'americana': 0.35,
    'singer-songwriter': 0.35,

    # Light (0.1-0.3)
    'pop': 0.25,
    'indie pop': 0.25,
    'synth-pop': 0.3,
    'new wave': 0.35,
    'power metal': 0.3,
    'symphonic metal': 0.35,
    'folk': 0.3,
    'acoustic': 0.25,
    'classical': 0.2,
    'neoclassical': 0.25,
    'chamber music': 0.2,
    'soul': 0.25,
    'r&b': 0.25,
    'funk': 0.2,
    'ska': 0.2,
    'ska punk': 0.25,
    'surf rock': 0.2,
    'rockabilly': 0.25,
    'swing': 0.2,
    'smooth jazz': 0.2,
    'lounge': 0.2,
    'easy listening': 0.15,
    'bossa nova': 0.2,
    'latin': 0.2,
    'flamenco': 0.3,
    'afrobeat': 0.25,
    'highlife': 0.2,
    'bluegrass': 0.25,
    'dancehall': 0.25,
    'reggaeton': 0.2,
    'trap': 0.4,
    'skate punk': 0.3,

    # Very light (0.0-0.2)
    'happy': 0.1,
    'uplifting': 0.1,
    'cheerful': 0.05,
    'summer': 0.15,
    'party': 0.2,
}

# Tempo keywords (relative, 0-1 scale)
TEMPO_KEYWORDS = {
    # Very fast (0.8-1.0)
    'grindcore': 1.0,
    'speedcore': 1.0,
    'gabber': 0.95,
    'thrash metal': 0.85,
    'crossover thrash': 0.85,
    'bay area thrash': 0.88,
    'teutonic thrash': 0.88,
    'blackened thrash': 0.86,
    'technical thrash': 0.88,
    'proto-thrash': 0.78,
    'death thrash': 0.86,
    'death metal': 0.8,
    'speed metal': 0.9,
    'powerviolence': 0.95,
    'drum and bass': 0.85,
    'hardcore techno': 0.9,
    'brutal death metal': 0.88,
    'war metal': 0.9,
    'bestial black metal': 0.9,
    'crust punk': 0.82,
    'd-beat': 0.85,
    'skate punk': 0.82,

    # Fast (0.6-0.8)
    'black metal': 0.75,
    'punk': 0.75,
    'hardcore': 0.7,
    'metalcore': 0.7,
    'power metal': 0.7,
    'techno': 0.7,
    'trance': 0.7,
    'old school death metal': 0.78,
    'swedish death metal': 0.78,
    'florida death metal': 0.82,
    'technical death metal': 0.75,
    'melodic death metal': 0.72,
    'symphonic black metal': 0.7,
    'melodic black metal': 0.72,
    'atmospheric black metal': 0.65,
    'blackgaze': 0.6,
    'post-black metal': 0.6,
    'industrial metal': 0.68,
    'aggrotech': 0.72,
    'electro-industrial': 0.65,
    'street punk': 0.72,
    'oi': 0.7,
    'ska punk': 0.72,
    'garage punk': 0.7,
    'psychobilly': 0.7,
    'noise rock': 0.65,
    'mathcore': 0.75,
    'black thrash': 0.82,
    'grime': 0.7,
    'trap': 0.7,
    'dancehall': 0.7,
    'reggaeton': 0.65,
    'free jazz': 0.6,
    'bebop': 0.65,
    'afrobeat': 0.65,
    'crossover': 0.78,

    # Medium (0.4-0.6)
    'heavy metal': 0.55,
    'rock': 0.5,
    'house': 0.55,
    'electronic': 0.5,
    'progressive metal': 0.5,
    'alternative': 0.5,
    'pop': 0.5,
    'post-punk': 0.5,
    'deathrock': 0.5,
    'gothic rock': 0.45,
    'gothic metal': 0.45,
    'new wave': 0.5,
    'synth-pop': 0.55,
    'ebm': 0.55,
    'industrial rock': 0.55,
    'garage rock': 0.6,
    'indie rock': 0.5,
    'indie': 0.5,
    'britpop': 0.5,
    'alternative rock': 0.5,
    'hard rock': 0.55,
    'surf rock': 0.55,
    'rockabilly': 0.6,
    'psychedelic rock': 0.5,
    'acid rock': 0.5,
    'krautrock': 0.5,
    'space rock': 0.45,
    'stoner rock': 0.45,
    'desert rock': 0.45,
    'blues rock': 0.5,
    'blues': 0.45,
    'jazz': 0.5,
    'swing': 0.55,
    'jazz fusion': 0.55,
    'jazz rock': 0.55,
    'funk': 0.6,
    'soul': 0.5,
    'r&b': 0.5,
    'hip-hop': 0.5,
    'rap': 0.5,
    'ska': 0.6,
    'reggae': 0.45,
    'folk metal': 0.55,
    'viking metal': 0.55,
    'pagan metal': 0.55,
    'progressive death metal': 0.6,
    'sludge': 0.4,
    'electroclash': 0.55,
    'electropunk': 0.6,
    'no wave': 0.55,
    'math rock': 0.55,
    'witch house': 0.4,
    'synthwave': 0.55,
    'latin': 0.55,
    'flamenco': 0.5,
    'highlife': 0.55,
    'bluegrass': 0.55,
    'country': 0.5,
    'americana': 0.45,
    'horror punk': 0.6,

    # Slow (0.2-0.4)
    'doom metal': 0.25,
    'sludge': 0.3,
    'stoner': 0.35,
    'trip-hop': 0.35,
    'downtempo': 0.3,
    'post-rock': 0.4,
    'shoegaze': 0.4,
    'coldwave': 0.35,
    'cold wave': 0.35,
    'minimal wave': 0.35,
    'darkwave': 0.35,
    'batcave': 0.42,
    'ethereal wave': 0.35,
    'ethereal': 0.35,
    'dream pop': 0.35,
    'neofolk': 0.35,
    'dark folk': 0.35,
    'apocalyptic folk': 0.32,
    'martial industrial': 0.3,
    'military pop': 0.35,
    'post-metal': 0.35,
    'stoner doom': 0.25,
    'epic doom': 0.25,
    'traditional doom': 0.25,
    'death doom': 0.3,
    'neoclassical darkwave': 0.3,
    'dark cabaret': 0.4,
    'gothic': 0.35,
    'cool jazz': 0.4,
    'smooth jazz': 0.35,
    'lounge': 0.4,
    'easy listening': 0.35,
    'bossa nova': 0.4,
    'dub': 0.35,
    'chillwave': 0.35,
    'vaporwave': 0.3,
    'lo-fi': 0.35,
    'singer-songwriter': 0.35,
    'folk': 0.35,
    'acoustic': 0.35,
    'glitch': 0.4,
    'world music': 0.4,
    'death industrial': 0.3,
    'power electronics': 0.4,

    # Very slow (0.0-0.2)
    'funeral doom': 0.1,
    'drone': 0.1,
    'ambient': 0.15,
    'dark ambient': 0.1,
    'meditation': 0.05,
    'drone doom': 0.08,
    'dungeon synth': 0.2,
    'ritual ambient': 0.15,
    'isolationism': 0.1,
    'field recordings': 0.1,
    'musique concrète': 0.15,
    'microsound': 0.1,
    'lowercase': 0.05,
    'classical': 0.3,
    'neoclassical': 0.25,
    'chamber music': 0.25,
}

# Texture keywords (busy vs sparse, complexity, 0-1 scale)
TEXTURE_KEYWORDS = {
    # Very dense (0.8-1.0)
    'grindcore': 1.0,
    'death metal': 0.9,
    'technical death metal': 0.95,
    'mathcore': 0.95,
    'progressive metal': 0.8,
    'symphonic metal': 0.85,
    'orchestral': 0.85,
    'noise': 0.9,
    'harsh noise': 0.95,
    'brutal death metal': 0.92,
    'war metal': 0.88,
    'bestial black metal': 0.88,
    'free jazz': 0.82,
    'progressive death metal': 0.85,
    'symphonic black metal': 0.82,

    'bay area thrash': 0.78,
    'teutonic thrash': 0.78,
    'blackened thrash': 0.80,
    'technical thrash': 0.90,
    'proto-thrash': 0.70,
    'death thrash': 0.83,
    'speed metal': 0.72,

    # Dense (0.6-0.8)
    'black metal': 0.75,
    'thrash metal': 0.75,
    'metalcore': 0.7,
    'power metal': 0.7,
    'drum and bass': 0.7,
    'industrial': 0.65,
    'atmospheric black metal': 0.7,
    'blackgaze': 0.7,
    'post-black metal': 0.68,
    'melodic black metal': 0.68,
    'old school death metal': 0.78,
    'swedish death metal': 0.75,
    'florida death metal': 0.8,
    'melodic death metal': 0.72,
    'deathcore': 0.72,
    'industrial metal': 0.7,
    'aggrotech': 0.65,
    'electro-industrial': 0.62,
    'power electronics': 0.7,
    'noise rock': 0.7,
    'math rock': 0.75,
    'shoegaze': 0.65,
    'psychedelic rock': 0.6,
    'acid rock': 0.65,
    'space rock': 0.6,
    'krautrock': 0.6,
    'progressive rock': 0.65,
    'jazz fusion': 0.7,
    'jazz rock': 0.65,
    'bebop': 0.65,
    'no wave': 0.65,
    'glitch': 0.6,
    'musique concrète': 0.65,
    'crust punk': 0.68,
    'd-beat': 0.65,
    'black thrash': 0.75,
    'crossover thrash': 0.72,
    'crossover': 0.7,
    'gothic metal': 0.6,
    'folk metal': 0.65,
    'viking metal': 0.6,
    'pagan metal': 0.6,
    'afrobeat': 0.65,

    # Medium (0.4-0.6)
    'heavy metal': 0.55,
    'rock': 0.5,
    'alternative': 0.5,
    'electronic': 0.5,
    'techno': 0.55,
    'house': 0.5,
    'post-metal': 0.5,
    'post-punk': 0.45,
    'coldwave': 0.35,
    'cold wave': 0.35,
    'deathrock': 0.45,
    'gothic rock': 0.45,
    'batcave': 0.45,
    'new wave': 0.45,
    'synth-pop': 0.45,
    'ebm': 0.5,
    'industrial rock': 0.55,
    'hard rock': 0.55,
    'alternative rock': 0.5,
    'indie rock': 0.45,
    'indie': 0.45,
    'britpop': 0.45,
    'garage rock': 0.5,
    'garage punk': 0.55,
    'punk': 0.55,
    'hardcore': 0.6,
    'stoner rock': 0.5,
    'desert rock': 0.5,
    'blues rock': 0.5,
    'blues': 0.45,
    'sludge': 0.5,
    'death doom': 0.55,
    'trance': 0.5,
    'synthwave': 0.45,
    'electroclash': 0.5,
    'electropunk': 0.5,
    'witch house': 0.45,
    'hip-hop': 0.5,
    'rap': 0.5,
    'grime': 0.55,
    'trap': 0.55,
    'ska': 0.5,
    'ska punk': 0.55,
    'reggae': 0.4,
    'funk': 0.55,
    'soul': 0.45,
    'r&b': 0.45,
    'jazz': 0.5,
    'cool jazz': 0.45,
    'swing': 0.5,
    'country': 0.4,
    'americana': 0.4,
    'bluegrass': 0.5,
    'latin': 0.5,
    'flamenco': 0.5,
    'highlife': 0.5,
    'psychobilly': 0.55,
    'horror punk': 0.5,
    'street punk': 0.5,
    'oi': 0.48,
    'skate punk': 0.52,
    'rockabilly': 0.45,
    'surf rock': 0.45,
    'dark cabaret': 0.5,
    'world music': 0.45,
    'powerviolence': 0.6,
    'speedcore': 0.55,
    'gabber': 0.55,
    'dancehall': 0.5,
    'reggaeton': 0.45,

    # Sparse (0.2-0.4)
    'doom metal': 0.35,
    'stoner': 0.4,
    'post-rock': 0.4,
    'trip-hop': 0.35,
    'folk': 0.35,
    'acoustic': 0.3,
    'darkwave': 0.35,
    'ethereal wave': 0.35,
    'ethereal': 0.35,
    'dream pop': 0.35,
    'neofolk': 0.3,
    'dark folk': 0.3,
    'apocalyptic folk': 0.3,
    'martial industrial': 0.35,
    'military pop': 0.3,
    'neoclassical darkwave': 0.35,
    'gothic': 0.35,
    'downtempo': 0.3,
    'chillout': 0.25,
    'stoner doom': 0.35,
    'epic doom': 0.35,
    'traditional doom': 0.35,
    'lo-fi': 0.3,
    'chillwave': 0.3,
    'vaporwave': 0.3,
    'dub': 0.35,
    'bossa nova': 0.3,
    'smooth jazz': 0.3,
    'lounge': 0.3,
    'easy listening': 0.25,
    'singer-songwriter': 0.3,
    'pop': 0.4,
    'indie pop': 0.35,
    'classical': 0.35,
    'neoclassical': 0.3,
    'chamber music': 0.35,
    'death industrial': 0.4,
    'funeral doom': 0.25,

    # Very sparse (0.0-0.2)
    'ambient': 0.15,
    'dark ambient': 0.1,
    'drone': 0.05,
    'minimal': 0.2,
    'minimalist': 0.15,
    'minimal wave': 0.25,
    'drone doom': 0.1,
    'dungeon synth': 0.2,
    'ritual ambient': 0.1,
    'isolationism': 0.08,
    'field recordings': 0.05,
    'meditation': 0.05,
    'sleep': 0.05,
    'microsound': 0.1,
    'lowercase': 0.05,
}


def score_dimension(tags: list[str], keyword_map: dict[str, float], default: float = 0.5) -> float:
    """Score a dimension based on tag matches."""
    if not tags:
        return default

    scores = []
    weights = []

    for tag in tags:
        tag_lower = tag.lower()

        # Exact match
        if tag_lower in keyword_map:
            scores.append(keyword_map[tag_lower])
            weights.append(1.0)
            continue

        # Partial match (tag contains keyword or keyword contains tag)
        for keyword, score in keyword_map.items():
            if keyword in tag_lower or tag_lower in keyword:
                scores.append(score)
                weights.append(0.5)  # Lower weight for partial matches
                break

    if not scores:
        return default

    # Weighted average
    total_weight = sum(weights)
    return sum(s * w for s, w in zip(scores, weights)) / total_weight


# Alias for backward compatibility
DENSITY_KEYWORDS = TEXTURE_KEYWORDS


def compute_track_profile(genres: list[str], tags: list[str]) -> dict[str, float]:
    """Compute semantic profile for a track from its genres and tags."""
    all_tags = genres + tags

    return {
        'energy': score_dimension(all_tags, ENERGY_KEYWORDS),
        'darkness': score_dimension(all_tags, DARKNESS_KEYWORDS),
        'tempo': score_dimension(all_tags, TEMPO_KEYWORDS),
        'texture': score_dimension(all_tags, TEXTURE_KEYWORDS),
    }


def get_track_tags(cur, track_id: str) -> tuple[list[str], list[str]]:
    """Get genres and Last.fm tags for a track."""
    # Get genres
    cur.execute("""
        SELECT g.name FROM genres g
        JOIN track_genres tg ON g.id = tg.genre_id
        WHERE tg.track_id = %s
    """, (track_id,))
    genres = [row[0] for row in cur.fetchall()]

    # Get Last.fm tags
    cur.execute("""
        SELECT lt.name FROM lastfm_tags lt
        JOIN track_lastfm_tags tlt ON lt.id = tlt.tag_id
        WHERE tlt.track_id = %s
        ORDER BY tlt.weight DESC
        LIMIT 20
    """, (track_id,))
    tags = [row[0] for row in cur.fetchall()]

    # If no track tags, try artist tags
    if not tags:
        cur.execute("""
            SELECT lt.name
            FROM lastfm_tags lt
            JOIN artist_lastfm_tags alt ON lt.id = alt.tag_id
            JOIN track_artists ta ON ta.artist_id = alt.artist_id
            WHERE ta.track_id = %s
            GROUP BY lt.name
            ORDER BY MAX(alt.weight) DESC, lt.name
            LIMIT 20
        """, (track_id,))
        tags = [row[0] for row in cur.fetchall()]

    return genres, tags


async def generate_profiles(
    progress_callback: callable = None,
    batch_size: int = 500,
    force: bool = False,
) -> dict[str, int]:
    """Generate semantic profiles for tracks that don't have them.

    Args:
        force: When True, regenerate profiles for ALL tracks, not just missing
               ones. Use this after updating keyword maps.

    Returns:
        Stats dict with counts
    """
    stats = {
        "processed": 0,
        "created": 0,
        "fallback": 0,
        "skipped": 0,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Get tracks to process
            if force:
                cur.execute("SELECT t.id FROM tracks t")
            else:
                cur.execute("""
                    SELECT t.id FROM tracks t
                    LEFT JOIN track_profiles tp ON t.id = tp.track_id
                    WHERE tp.track_id IS NULL
                """)
            track_ids = [row[0] for row in cur.fetchall()]

            if not track_ids:
                logger.info("All tracks have profiles")
                return stats

            logger.info(f"Generating profiles for {len(track_ids)} tracks")

            if progress_callback:
                progress_callback(0, len(track_ids), f"Generating profiles for {len(track_ids)} tracks...")

            for i, track_id in enumerate(track_ids):
                genres, tags = get_track_tags(cur, str(track_id))

                if not genres and not tags:
                    # Insert a neutral fallback profile so the track can still
                    # participate in trajectory scoring
                    cur.execute("""
                        INSERT INTO track_profiles (track_id, energy, darkness, tempo, texture)
                        VALUES (%s, 0.5, 0.5, 0.5, 0.5)
                        ON CONFLICT (track_id) DO NOTHING
                    """, (track_id,))
                    stats["fallback"] += 1
                    stats["processed"] += 1
                    continue

                profile = compute_track_profile(genres, tags)

                cur.execute("""
                    INSERT INTO track_profiles (track_id, energy, darkness, tempo, texture)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (track_id) DO UPDATE SET
                        energy = EXCLUDED.energy,
                        darkness = EXCLUDED.darkness,
                        tempo = EXCLUDED.tempo,
                        texture = EXCLUDED.texture,
                        computed_at = now()
                """, (track_id, profile['energy'], profile['darkness'],
                      profile['tempo'], profile['texture']))

                stats["created"] += 1
                stats["processed"] += 1

                # Commit and report progress
                if (i + 1) % batch_size == 0:
                    conn.commit()
                    if progress_callback:
                        progress_callback(i + 1, len(track_ids), f"Generated {i + 1}/{len(track_ids)} profiles")
                    logger.info(f"Generated {i + 1}/{len(track_ids)} profiles")

            conn.commit()

    logger.info(f"Profile generation complete: {stats}")
    return stats
