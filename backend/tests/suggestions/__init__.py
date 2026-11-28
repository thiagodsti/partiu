# Wikipedia articles the suggestion tests pretend exist (see conftest.py).
ARTICLES = {
    "Torre de Belém": {
        "image_url": "https://upload.wikimedia.org/belem.jpg",
        "page_url": "https://en.wikipedia.org/wiki/Bel%C3%A9m_Tower",
        "lat": 38.6916,
        "lon": -9.2160,
    },
    "Time Out Market": {
        "image_url": None,
        "page_url": "https://en.wikipedia.org/wiki/Time_Out_Market_Lisboa",
        "lat": 38.7069,
        "lon": -9.1459,
    },
    # The same building under its other name.
    "Mercado da Ribeira": {
        "image_url": None,
        "page_url": "https://en.wikipedia.org/wiki/Time_Out_Market_Lisboa",
        "lat": 38.7070,
        "lon": -9.1460,
    },
}
