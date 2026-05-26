import flask
from src.core.config import server


def _cors_origin():
    """Devuelve el origen exacto de la petición (incluido 'null' para file://)."""
    return flask.request.headers.get('Origin') or '*'


@server.route('/api/html-to-pdf', methods=['OPTIONS'])
def html_to_pdf_preflight():
    resp = flask.make_response()
    resp.headers['Access-Control-Allow-Origin'] = _cors_origin()
    resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    resp.headers['Vary'] = 'Origin'
    return resp


@server.route('/api/html-to-pdf', methods=['POST'])
def html_to_pdf_endpoint():
    from playwright.sync_api import sync_playwright
    html_content = flask.request.get_data(as_text=True)
    if not html_content:
        return flask.make_response('No HTML recibido', 400)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.set_content(html_content, wait_until='networkidle')
        page.wait_for_timeout(2000)
        pdf_bytes = page.pdf(
            format='A4', print_background=True,
            margin={'top': '1.5cm', 'bottom': '1.5cm', 'left': '1.2cm', 'right': '1.2cm'},
        )
        browser.close()
    resp = flask.make_response(pdf_bytes)
    resp.headers['Content-Type'] = 'application/pdf'
    resp.headers['Content-Disposition'] = 'attachment; filename=informe.pdf'
    resp.headers['Access-Control-Allow-Origin'] = _cors_origin()
    resp.headers['Vary'] = 'Origin'
    return resp
