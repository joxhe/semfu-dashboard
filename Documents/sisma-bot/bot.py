"""
Bot RPA - SISMA → Google Sheets + Dashboard HTML
Fundación Sembrando Futuro (SEMFU)
"""

import time
import datetime
import sys
import re
import smtplib
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import gspread
from google.oauth2.service_account import Credentials
from github import Github, Auth
from zoneinfo import ZoneInfo

COLOMBIA_TZ = ZoneInfo("America/Bogota")

# ══════════════════════════════════════════════════════
# CONFIGURACIÓN
# Las 3 credenciales sensibles se leen del entorno si están disponibles
# (GitHub Actions), y usan el valor hardcodeado como fallback (PC local).
# ══════════════════════════════════════════════════════
SISMA_URL      = "https://sembrandofuturo.sismacorporation.com/SismaSalud/ips/iniciando.php"
SISMA_USUARIO  = "Jlruizo"
SISMA_PASSWORD = os.environ.get("SISMA_PASSWORD", "semfu.2025")

GOOGLE_CREDENTIALS = "credentials.json"
SHEET_ID           = "1rpxY82zhKiYOKfoD3qkB7uHNkAQs-aJ9b6rjyoLdEAI"

EMAIL_REMITENTE    = "jose.ruizo@cecar.edu.co"
EMAIL_CONTRASENA   = os.environ.get("EMAIL_CONTRASENA", "ksyo wjmi yzpc dydp")
EMAIL_DESTINATARIO = "jose.ruizo@cecar.edu.co"
SHEET_URL          = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"

GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN_BOT", "")  # Token va en secret de GitHub, no aquí
GITHUB_REPO        = "joxhe/semfu-dashboard"
GITHUB_PAGES_URL   = "https://joxhe.github.io/semfu-dashboard"

# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════
def log(msg):
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def fecha_hoy():
    return datetime.datetime.now(COLOMBIA_TZ).strftime("%Y/%m/%d")

def nombre_hoja_hoy():
    return datetime.datetime.now(COLOMBIA_TZ).strftime("%d-%m-%Y")

def cerrar_alert_si_existe(driver):
    try:
        alert = driver.switch_to.alert
        log(f"⚠ Alerta del sistema: '{alert.text}' — cerrando...")
        alert.accept()
    except Exception:
        pass

def esperar_y_click(driver, by, selector, timeout=15, descripcion="elemento"):
    wait = WebDriverWait(driver, timeout)
    elemento = wait.until(EC.element_to_be_clickable((by, selector)))
    driver.execute_script("arguments[0].scrollIntoView(true);", elemento)
    time.sleep(0.3)
    elemento.click()
    log(f"Click en: {descripcion} ✓")
    return elemento

# ══════════════════════════════════════════════════════
# SELENIUM — Login y extracción
# ══════════════════════════════════════════════════════
def iniciar_driver():
    log("Iniciando Chrome...")
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=1920,1080")
    options.set_capability("unhandledPromptBehavior", "accept")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    return driver

def login(driver):
    log("Abriendo SISMA...")
    driver.get(SISMA_URL)
    wait = WebDriverWait(driver, 20)

    log("Seleccionando Aplicación: Asistencial...")
    select_app = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//select[option[contains(text(),'Asistencial')]]")
    ))
    Select(select_app).select_by_visible_text("Asistencial")
    time.sleep(1)

    log("Seleccionando Conexión: SEMBRANDO FUTURO IPS...")
    select_con = driver.find_element(
        By.XPATH, "//select[option[contains(text(),'SEMBRANDO FUTURO IPS')]]"
    )
    Select(select_con).select_by_visible_text("SEMBRANDO FUTURO IPS")
    time.sleep(1)

    log("Ingresando credenciales...")
    campo_usuario = driver.find_element(By.XPATH, "//input[@placeholder='Nombre de Usuario']")
    campo_usuario.clear()
    campo_usuario.send_keys(SISMA_USUARIO)
    campo_pass = driver.find_element(By.XPATH, "//input[@placeholder='Contraseña']")
    campo_pass.clear()
    campo_pass.send_keys(SISMA_PASSWORD)
    driver.find_element(By.ID, "btnEnviar").click()

    log("Seleccionando punto de atención: FUNDACION SEMBRANDO FUTURO (Sincelejo)...")
    punto = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//td[contains(text(),'FUNDACION SEMBRANDO FUTURO') and not(contains(text(),'TOLU') or contains(text(),'SAN ONOFRE') or contains(text(),'SINCE') or contains(text(),'COLOSO'))]")
    ))
    punto.click()
    log("Punto de atención seleccionado ✓")
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(5)
    cerrar_alert_si_existe(driver)
    log("Login exitoso ✓")

def esperar_contenido_dinamico(driver, timeout=30):
    log("Esperando iframe topFrame...")
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            n = driver.execute_script("""
                var iframe = document.querySelector('#topFrame');
                if (!iframe || !iframe.contentDocument) return 0;
                return iframe.contentDocument.querySelectorAll('a[onclick]').length;
            """)
            if n > 10:
                log(f"iframe topFrame listo ({n} links) ✓")
                return True
        except Exception:
            cerrar_alert_si_existe(driver)
        time.sleep(1)
    return False

def ir_a_consolidados(driver):
    log("Haciendo clic en Consolidados...")
    esperar_contenido_dinamico(driver)
    cerrar_alert_si_existe(driver)
    time.sleep(1)
    resultado = driver.execute_script("""
        var iframe = document.querySelector('#topFrame');
        if (!iframe || !iframe.contentDocument) return 'sin iframe';
        var links = Array.from(iframe.contentDocument.querySelectorAll('a[onclick]'));
        var consolidados = links.find(a => a.getAttribute('onclick').includes('148'));
        if (!consolidados) return 'sin elemento';
        consolidados.click();
        return 'ok';
    """)
    if resultado != 'ok':
        raise Exception(f"No se pudo hacer click en Consolidados: {resultado}")
    log("Módulo Consolidados abierto ✓")
    time.sleep(2)

def generar_informe(driver, fecha=None):
    hoy = fecha if fecha else fecha_hoy()
    url_reporte = (
        "https://sembrandofuturo.sismacorporation.com/SismaSalud/Reportes/Cliente//html/"
        "consolidados/estadisticas_citas.php"
        f"?autoid=&todosPaci=1&cod_med=&todosMedi=1&idEmpresa=&todosEmp=1"
        f"&idEspecialidad=&todosEsp=1&inicial={hoy}&final={hoy}&mostrar=A&detallarPago=1"
    )
    log(f"Navegando a reporte: {hoy}")
    try:
        driver.get(url_reporte)
    except Exception:
        pass
    cerrar_alert_si_existe(driver)
    wait = WebDriverWait(driver, 30)
    try:
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        log("Reporte cargado ✓")
    except Exception:
        log("⚠ Timeout esperando tabla")
    time.sleep(2)

def extraer_datos(driver):
    log("Extrayendo datos...")
    WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
    time.sleep(1)
    resultado = driver.execute_script("""
        var tablas = Array.from(document.querySelectorAll('table'));
        var tabla = tablas.reduce((a, b) =>
            a.querySelectorAll('tr').length >= b.querySelectorAll('tr').length ? a : b);
        var encabezados = [];
        var datos = [];
        tabla.querySelectorAll('tr').forEach(function(fila) {
            var heads = fila.querySelectorAll('td.head');
            if (heads.length > 0 && encabezados.length === 0) {
                heads.forEach(function(c) {
                    if (!c.classList.contains('ocultar'))
                        encabezados.push(c.innerText.trim().replace(/\\n/g, ' '));
                });
                return;
            }
            var todasCeldas = Array.from(fila.querySelectorAll('td'));
            if (todasCeldas.some(c => c.classList.contains('head'))) return;
            var celdas = todasCeldas.filter(c => !c.classList.contains('ocultar'));
            if (celdas.length === 0) return;
            var valores = celdas.map(c => c.innerText.trim().replace(/\\n/g, ' '));
            if (valores.some(v => v !== '')) datos.push(valores);
        });
        return {encabezados: encabezados, datos: datos};
    """)
    encabezados = resultado["encabezados"]
    datos = [f for f in resultado["datos"] if len(f) == len(encabezados)]
    log(f"Extraídas: {len(datos)} filas, {len(encabezados)} columnas ✓")
    return encabezados, datos

# ══════════════════════════════════════════════════════
# GOOGLE SHEETS
# ══════════════════════════════════════════════════════
def conectar_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS, scopes=scopes)
    return gspread.authorize(creds)

def obtener_o_crear_hoja(spreadsheet, nombre_hoja):
    hojas = [h.title for h in spreadsheet.worksheets()]
    if nombre_hoja in hojas:
        log(f"Hoja '{nombre_hoja}' ya existe ✓")
        return spreadsheet.worksheet(nombre_hoja)
    nueva = spreadsheet.add_worksheet(title=nombre_hoja, rows=1000, cols=30)
    log(f"Hoja '{nombre_hoja}' creada ✓")
    return nueva

def formatear_hoja(spreadsheet, nombre_hoja, num_columnas, num_filas):
    """Aplica formato visual: encabezado azul, filas alternadas con color fijo, bordes, columnas anchas."""
    try:
        sheet = spreadsheet.worksheet(nombre_hoja)
        sheet_id = sheet.id

        COLOR_AZUL_HEADER  = {"red": 0.0,  "green": 0.36, "blue": 0.66}
        COLOR_BLANCO       = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
        COLOR_FILA_PAR     = {"red": 0.93, "green": 0.96, "blue": 1.0}
        COLOR_FILA_IMPAR   = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
        COLOR_BORDE        = {"red": 0.85, "green": 0.85, "blue": 0.85}

        requests = []

        # 1. Encabezado azul institucional (fila 1)
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": num_columnas
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_AZUL_HEADER,
                        "textFormat": {
                            "foregroundColor": COLOR_BLANCO,
                            "bold": True,
                            "fontSize": 10
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE"
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        })

        # 2. Filas alternadas con color fijo (sin fórmula condicional)
        for i in range(num_filas):
            row_index = i + 1
            color = COLOR_FILA_PAR if i % 2 == 0 else COLOR_FILA_IMPAR
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_index,
                        "endRowIndex": row_index + 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": num_columnas
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                            "textFormat": {"fontSize": 10},
                            "verticalAlignment": "MIDDLE"
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)"
                }
            })

        # 3. Altura de fila encabezado
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0, "endIndex": 1
                },
                "properties": {"pixelSize": 32},
                "fields": "pixelSize"
            }
        })

        # 4. Altura de filas de datos
        if num_filas > 0:
            requests.append({
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 1, "endIndex": num_filas + 1
                    },
                    "properties": {"pixelSize": 22},
                    "fields": "pixelSize"
                }
            })

        # 5. Bordes en toda la tabla
        borde = {"style": "SOLID", "color": COLOR_BORDE}
        requests.append({
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0, "endRowIndex": num_filas + 1,
                    "startColumnIndex": 0, "endColumnIndex": num_columnas
                },
                "innerHorizontal": borde,
                "innerVertical": borde,
                "bottom": {"style": "SOLID", "color": {"red": 0.7, "green": 0.7, "blue": 0.7}},
                "top":    borde,
                "left":   borde,
                "right":  borde
            }
        })

        # 6. Ancho automático de columnas
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": num_columnas
                }
            }
        })

        # 7. Congelar fila de encabezado
        requests.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1}
                },
                "fields": "gridProperties.frozenRowCount"
            }
        })

        spreadsheet.batch_update({"requests": requests})
        log(f"Formato aplicado a '{nombre_hoja}' ✓")

    except Exception as e:
        log(f"⚠ No se pudo aplicar formato: {e}")


def exportar_a_sheets(encabezados, datos, nombre_hoja=None):
    if nombre_hoja is None:
        nombre_hoja = nombre_hoja_hoy()
    cliente = conectar_sheets()
    spreadsheet = cliente.open_by_key(SHEET_ID)
    sheet = obtener_o_crear_hoja(spreadsheet, nombre_hoja)
    sheet.clear()
    encabezados_con_fecha = ["FECHA EXTRACCIÓN"] + encabezados
    sheet.insert_row(encabezados_con_fecha, index=1)
    log("Encabezados escritos ✓")
    fecha_extraccion = datetime.datetime.now(COLOMBIA_TZ).strftime("%Y-%m-%d %H:%M")
    filas = [[fecha_extraccion] + fila for fila in datos]
    if filas:
        sheet.append_rows(filas, value_input_option="USER_ENTERED")
        log(f"✅ {len(filas)} filas escritas en '{nombre_hoja}'")
    formatear_hoja(spreadsheet, nombre_hoja, len(encabezados_con_fecha), len(filas))
    return len(filas)

# ══════════════════════════════════════════════════════
# HISTORIAL — Opción B: leer directo de hojas dd-mm-yyyy
# ══════════════════════════════════════════════════════
def obtener_historial_dashboard():
    """
    Recorre todas las hojas con formato dd-mm-yyyy del Sheet,
    cuenta las filas de datos de cada una y construye el historial.
    No depende de ninguna hoja de resumen — es la fuente de verdad.
    """
    try:
        cliente = conectar_sheets()
        spreadsheet = cliente.open_by_key(SHEET_ID)
        patron = re.compile(r"^\d{2}-\d{2}-\d{4}$")

        hojas_fechas = []
        for hoja in spreadsheet.worksheets():
            if patron.match(hoja.title):
                try:
                    fecha_obj = datetime.datetime.strptime(hoja.title, "%d-%m-%Y").date()
                    hojas_fechas.append((fecha_obj, hoja.title))
                except ValueError:
                    pass

        hojas_fechas.sort(key=lambda x: x[0])
        hojas_fechas = hojas_fechas[-7:]

        historial = []
        for fecha_obj, nombre in hojas_fechas:
            try:
                hoja = spreadsheet.worksheet(nombre)
                todas_filas = hoja.get_all_values()
                total = max(0, len(todas_filas) - 1)
                if total > 0:
                    historial.append({
                        "fecha": nombre,
                        "total": total
                    })
                    log(f"Historial: {nombre} → {total} pacientes ✓")
            except Exception as e:
                log(f"⚠ No se pudo leer hoja '{nombre}': {e}")

        return historial

    except Exception as e:
        log(f"⚠ No se pudo construir historial: {e}")
        return []

# ══════════════════════════════════════════════════════
# ANÁLISIS DE DATOS
# ══════════════════════════════════════════════════════
def analizar_datos(encabezados, datos):
    conteos_eps = {}
    idx_contrato = None
    for i, col in enumerate(encabezados):
        if "CONTRATO" in col.upper():
            idx_contrato = i
            break
    if idx_contrato is not None:
        for fila in datos:
            if idx_contrato < len(fila):
                eps = fila[idx_contrato].strip()
                if eps:
                    conteos_eps[eps] = conteos_eps.get(eps, 0) + 1
    return conteos_eps

# ══════════════════════════════════════════════════════
# DASHBOARD HTML
# ══════════════════════════════════════════════════════
def generar_dashboard_html(nombre_hoja, total, conteos_eps, historial):
    """
    El dashboard v2 es autocontenido — consulta el Apps Script en tiempo real.
    Lee el HTML desde dashboard_template.html y lo copia como dashboard.html.
    Los parámetros nombre_hoja/total/conteos_eps/historial se conservan por
    compatibilidad, pero no se inyectan: el navegador los carga vía API.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    ruta_template = os.path.join(base, "dashboard_template.html")
    ruta_salida   = os.path.join(base, "dashboard.html")

    with open(ruta_template, "r", encoding="utf-8") as f:
        html = f.read()

    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html)
    log("Dashboard HTML v2 listo ✓")
    return ruta_salida

# ══════════════════════════════════════════════════════
# GITHUB PAGES — Subir dashboard y obtener link
# ══════════════════════════════════════════════════════
_OLD_INLINE_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard SISMA — SEMFU</title>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --azul:#005CA9; --azul-claro:#00A8E0; --verde:#8CC63F;
      --magenta:#E6007E; --naranja:#F7941D;
      --bg:#f0f4f8; --card:#ffffff; --texto:#1a2332;
      --muted:#7a8a9a; --borde:#e2e8f0; --radio:14px;
      --shadow:0 2px 12px rgba(0,0,0,.07);
    }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--texto); }
    .header {
      background:linear-gradient(135deg,var(--azul) 0%,var(--azul-claro) 100%);
      padding:0 40px; display:flex; align-items:center;
      justify-content:space-between; height:72px;
      position:sticky; top:0; z-index:100;
      box-shadow:0 2px 16px rgba(0,92,169,.25);
    }
    .header-left { display:flex; align-items:center; gap:14px; }
    .header-icon {
      width:44px; height:44px; background:rgba(255,255,255,.2);
      border-radius:10px; display:flex; align-items:center;
      justify-content:center; font-size:22px;
    }
    .header h1 { font-size:18px; font-weight:700; color:white; }
    .header-sub { font-size:12px; color:rgba(255,255,255,.7); margin-top:1px; }
    .header-badge {
      background:rgba(255,255,255,.2); color:white; font-size:11px;
      font-family:'DM Mono',monospace; padding:4px 12px;
      border-radius:20px; border:1px solid rgba(255,255,255,.3);
    }
    .container { max-width:1160px; margin:0 auto; padding:28px 24px 48px; }
    .filtro-card {
      background:var(--card); border-radius:var(--radio);
      padding:20px 24px; box-shadow:var(--shadow); margin-bottom:24px;
      display:flex; align-items:center; gap:16px; flex-wrap:wrap;
    }
    .filtro-label {
      font-size:12px; font-weight:600; color:var(--muted);
      text-transform:uppercase; letter-spacing:.6px; white-space:nowrap;
    }
    .atajos { display:flex; gap:8px; flex-wrap:wrap; }
    .atajo-btn {
      background:var(--bg); border:1.5px solid var(--borde);
      color:var(--texto); font-family:'DM Sans',sans-serif;
      font-size:13px; font-weight:500; padding:7px 14px;
      border-radius:8px; cursor:pointer; transition:all .15s;
    }
    .atajo-btn:hover { border-color:var(--azul); color:var(--azul); background:#eef5ff; }
    .atajo-btn.activo { background:var(--azul); color:white; border-color:var(--azul); }
    .separador { width:1px; height:32px; background:var(--borde); }
    .rango-inputs { display:flex; align-items:center; gap:8px; }
    .rango-inputs input[type="date"] {
      border:1.5px solid var(--borde); border-radius:8px;
      padding:7px 12px; font-family:'DM Sans',sans-serif;
      font-size:13px; color:var(--texto); background:var(--bg); outline:none;
    }
    .rango-inputs input[type="date"]:focus { border-color:var(--azul); }
    .rango-sep { font-size:13px; color:var(--muted); }
    .btn-aplicar {
      background:var(--azul); color:white; border:none;
      font-family:'DM Sans',sans-serif; font-size:13px; font-weight:600;
      padding:8px 18px; border-radius:8px; cursor:pointer; white-space:nowrap;
    }
    .btn-aplicar:hover { background:#004a8a; }
    .estado { text-align:center; padding:60px 20px; color:var(--muted); font-size:14px; display:none; }
    .estado.visible { display:block; }
    .spinner {
      width:36px; height:36px; border:3px solid var(--borde);
      border-top-color:var(--azul); border-radius:50%;
      animation:spin .7s linear infinite; margin:0 auto 12px;
    }
    @keyframes spin { to { transform:rotate(360deg); } }
    .kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-bottom:24px; }
    .kpi {
      background:var(--card); border-radius:var(--radio);
      padding:20px 22px; box-shadow:var(--shadow);
      border-left:4px solid var(--color); transition:transform .15s;
    }
    .kpi:hover { transform:translateY(-2px); }
    .kpi-icon { font-size:22px; margin-bottom:8px; }
    .kpi-label { font-size:11px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
    .kpi-value { font-size:38px; font-weight:700; color:var(--color); line-height:1; margin:6px 0 4px; }
    .kpi-sub { font-size:12px; color:var(--muted); }
    .charts-grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }
    .chart-card { background:var(--card); border-radius:var(--radio); padding:24px; box-shadow:var(--shadow); }
    .chart-card.full { grid-column:1 / -1; }
    .chart-header {
      display:flex; align-items:center; justify-content:space-between;
      margin-bottom:20px; padding-bottom:14px; border-bottom:1px solid var(--borde);
    }
    .chart-title { font-size:14px; font-weight:600; color:var(--texto); }
    .chart-badge {
      font-size:11px; font-family:'DM Mono',monospace;
      background:var(--bg); color:var(--muted); padding:3px 10px; border-radius:6px;
    }
    canvas { max-height:260px; }
    .tables-grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:24px; }
    .table-card { background:var(--card); border-radius:var(--radio); padding:24px; box-shadow:var(--shadow); }
    .table-card.full { grid-column:1 / -1; }
    .table-scroll { overflow-x:auto; }
    table { width:100%; border-collapse:collapse; }
    thead tr { background:#f7faff; }
    th {
      padding:10px 14px; text-align:left; font-size:11px; font-weight:600;
      color:var(--muted); text-transform:uppercase; letter-spacing:.5px;
      border-bottom:2px solid var(--borde); white-space:nowrap;
    }
    td { padding:10px 14px; font-size:13px; border-bottom:1px solid #f4f6f8; }
    tr:last-child td { border-bottom:none; }
    tbody tr:hover td { background:#f7fbff; }
    .pill {
      display:inline-block; padding:3px 10px; border-radius:20px;
      font-size:12px; font-weight:600; font-family:'DM Mono',monospace;
    }
    .pill-azul  { background:#dbeeff; color:var(--azul); }
    .pill-verde { background:#eaf6d6; color:#5a9000; }
    .bar-inline { display:flex; align-items:center; gap:8px; }
    .bar-inline-fill { height:6px; border-radius:3px; background:var(--azul); min-width:4px; }
    .acciones { display:flex; gap:12px; justify-content:center; margin-bottom:28px; }
    .btn-accion {
      display:inline-flex; align-items:center; gap:8px;
      padding:11px 22px; border-radius:9px; font-family:'DM Sans',sans-serif;
      font-size:14px; font-weight:600; text-decoration:none; cursor:pointer;
      border:none; transition:all .15s;
    }
    .btn-sheets { background:var(--azul); color:white; }
    .btn-sheets:hover { background:#004a8a; }
    .footer { text-align:center; font-size:12px; color:var(--muted); font-family:'DM Mono',monospace; padding-bottom:16px; }
    .sin-datos { text-align:center; padding:40px 20px; color:var(--muted); font-size:14px; }
    @media (max-width:768px) {
      .header { padding:0 16px; }
      .kpis { grid-template-columns:1fr 1fr; }
      .charts-grid,.tables-grid { grid-template-columns:1fr; }
      .chart-card.full,.table-card.full { grid-column:1; }
    }
  </style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="header-icon">🏥</div>
    <div>
      <div style="font-size:18px;font-weight:700;color:white">Dashboard SISMA — SEMFU</div>
      <div class="header-sub">Fundación Sembrando Futuro</div>
    </div>
  </div>
  <div class="header-badge" id="rangoActivo">Cargando…</div>
</div>

<div class="container">
  <div class="filtro-card">
    <span class="filtro-label">Período</span>
    <div class="atajos">
      <button class="atajo-btn" onclick="aplicarAtajo(7,this)">Últ. 7 días</button>
      <button class="atajo-btn" onclick="aplicarAtajo(14,this)">Últ. 14 días</button>
      <button class="atajo-btn" onclick="aplicarAtajo(30,this)">Últ. 30 días</button>
      <button class="atajo-btn" onclick="aplicarAtajo(0,this)">Este mes</button>
    </div>
    <div class="separador"></div>
    <div class="rango-inputs">
      <input type="date" id="fechaInicio">
      <span class="rango-sep">→</span>
      <input type="date" id="fechaFin">
      <button class="btn-aplicar" onclick="cargarDatos()">Aplicar</button>
    </div>
  </div>

  <div class="estado" id="estadoCarga">
    <div class="spinner"></div>Consultando datos…
  </div>

  <div id="contenido" style="display:none">
    <div class="kpis">
      <div class="kpi" style="--color:var(--azul)">
        <div class="kpi-icon">👥</div>
        <div class="kpi-label">Total pacientes</div>
        <div class="kpi-value" id="kpiTotal">—</div>
        <div class="kpi-sub">en el período</div>
      </div>
      <div class="kpi" style="--color:var(--verde)">
        <div class="kpi-icon">📅</div>
        <div class="kpi-label">Promedio diario</div>
        <div class="kpi-value" id="kpiPromedio">—</div>
        <div class="kpi-sub">pacientes / día</div>
      </div>
      <div class="kpi" style="--color:var(--magenta)">
        <div class="kpi-icon">🏆</div>
        <div class="kpi-label">Día pico</div>
        <div class="kpi-value" id="kpiMax">—</div>
        <div class="kpi-sub" id="kpiMaxFecha">máximo registrado</div>
      </div>
      <div class="kpi" style="--color:var(--naranja)">
        <div class="kpi-icon">🏥</div>
        <div class="kpi-label">EPS principal</div>
        <div class="kpi-value" id="kpiEPS" style="font-size:16px;margin-top:8px;line-height:1.3">—</div>
        <div class="kpi-sub">mayor volumen</div>
      </div>
    </div>

    <div class="charts-grid">
      <div class="chart-card">
        <div class="chart-header">
          <div class="chart-title">🥧 Distribución por EPS / Contrato</div>
          <div class="chart-badge" id="badgeTorta">—</div>
        </div>
        <canvas id="chartTorta"></canvas>
      </div>
      <div class="chart-card">
        <div class="chart-header">
          <div class="chart-title">🏥 Atenciones por Especialidad</div>
          <div class="chart-badge" id="badgeEsp">—</div>
        </div>
        <canvas id="chartEsp"></canvas>
      </div>
      <div class="chart-card full">
        <div class="chart-header">
          <div class="chart-title">📈 Evolución diaria de atenciones</div>
          <div class="chart-badge" id="badgeLinea">—</div>
        </div>
        <canvas id="chartLinea"></canvas>
      </div>
    </div>

    <div class="tables-grid">
      <div class="table-card">
        <div class="chart-header"><div class="chart-title">📋 Por EPS / Contrato</div></div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Contrato</th><th>Pacientes</th><th>%</th><th>Dist.</th></tr></thead>
            <tbody id="tablaEPS"></tbody>
          </table>
        </div>
      </div>
      <div class="table-card">
        <div class="chart-header"><div class="chart-title">👨‍⚕️ Por Médico</div></div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Médico</th><th>Pacientes</th><th>%</th></tr></thead>
            <tbody id="tablaMedico"></tbody>
          </table>
        </div>
      </div>
      <div class="table-card full">
        <div class="chart-header"><div class="chart-title">🔬 Por Especialidad Médica</div></div>
        <div class="table-scroll">
          <table>
            <thead><tr><th>Especialidad</th><th>Pacientes</th><th>%</th><th>Distribución</th></tr></thead>
            <tbody id="tablaEsp"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="acciones">
      <a href="https://docs.google.com/spreadsheets/d/1rpxY82zhKiYOKfoD3qkB7uHNkAQs-aJ9b6rjyoLdEAI"
         target="_blank" class="btn-accion btn-sheets">📊 Ver en Google Sheets</a>
    </div>
    <div class="footer" id="footerTs">—</div>
  </div>
</div>

<script>
const API_URL = "https://script.google.com/macros/s/AKfycbyRVqB1mKsOJSh4vrajp3pT-Jb5nkEpPoat3EgW1X9uxrrOreqU-bK9jz_0h5rvAkX-/exec";
const COLORES = ["#005CA9","#8CC63F","#E6007E","#00A8E0","#F7941D","#6B4C9A","#00B09B","#FF6B6B","#FFD166","#06D6A0","#118AB2","#EF476F"];
let chartTorta=null, chartEsp=null, chartLinea=null;

function hoy() { return new Date().toISOString().split("T")[0]; }
function restarDias(d) { const x=new Date(); x.setDate(x.getDate()-d); return x.toISOString().split("T")[0]; }
function primerDiaMes() { const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-01`; }
function iso2dd(iso) { const [y,m,d]=iso.split("-"); return `${d}-${m}-${y}`; }

function aplicarAtajo(dias, btn) {
  document.querySelectorAll(".atajo-btn").forEach(b=>b.classList.remove("activo"));
  btn.classList.add("activo");
  document.getElementById("fechaInicio").value = dias===0 ? primerDiaMes() : restarDias(dias-1);
  document.getElementById("fechaFin").value = hoy();
  cargarDatos();
}

async function cargarDatos() {
  const inicio=document.getElementById("fechaInicio").value;
  const fin=document.getElementById("fechaFin").value;
  if (!inicio||!fin) return;
  document.getElementById("contenido").style.display="none";
  document.getElementById("estadoCarga").classList.add("visible");
  const iF=iso2dd(inicio), fF=iso2dd(fin);
  document.getElementById("rangoActivo").textContent=`${iF} → ${fF}`;
  try {
    const resp=await fetch(`${API_URL}?inicio=${iF}&fin=${fF}`);
    const data=await resp.json();
    renderizar(data);
  } catch(e) {
    document.getElementById("estadoCarga").innerHTML=`<div style="color:#c0392b">⚠ Error al consultar datos.<br><small>${e.message}</small></div>`;
    return;
  }
  document.getElementById("estadoCarga").classList.remove("visible");
  document.getElementById("contenido").style.display="block";
}

function renderizar(data) {
  const total=data.total||0, eps=data.conteoEPS||{}, medicos=data.conteoMedico||{}, esps=data.conteoEsp||{}, hist=data.historial||[];
  document.getElementById("kpiTotal").textContent=total.toLocaleString("es");
  const prom=hist.length>0?Math.round(total/hist.length*10)/10:0;
  document.getElementById("kpiPromedio").textContent=prom;
  if (hist.length>0) {
    const pico=hist.reduce((a,b)=>a.total>=b.total?a:b);
    document.getElementById("kpiMax").textContent=pico.total;
    document.getElementById("kpiMaxFecha").textContent=pico.fecha;
  }
  const epsTop=Object.entries(eps).sort((a,b)=>b[1]-a[1])[0];
  if (epsTop) document.getElementById("kpiEPS").textContent=epsTop[0].replace("CONTRATO ","").substring(0,22);
  document.getElementById("badgeTorta").textContent=`${Object.keys(eps).length} contratos`;
  document.getElementById("badgeEsp").textContent=`${Object.keys(esps).length} especialidades`;
  document.getElementById("badgeLinea").textContent=`${hist.length} días`;

  if (chartTorta) chartTorta.destroy();
  chartTorta=new Chart(document.getElementById("chartTorta"),{
    type:"doughnut",
    data:{labels:Object.keys(eps),datasets:[{data:Object.values(eps),backgroundColor:COLORES.slice(0,Object.keys(eps).length),borderWidth:2,borderColor:"#fff"}]},
    options:{responsive:true,plugins:{legend:{position:"bottom",labels:{font:{size:11,family:"DM Sans"},padding:12}}}}
  });

  const espE=Object.entries(esps).sort((a,b)=>b[1]-a[1]).slice(0,8);
  if (chartEsp) chartEsp.destroy();
  chartEsp=new Chart(document.getElementById("chartEsp"),{
    type:"bar",
    data:{labels:espE.map(e=>e[0]),datasets:[{label:"Pacientes",data:espE.map(e=>e[1]),backgroundColor:COLORES.slice(0,espE.length),borderRadius:6,borderSkipped:false}]},
    options:{indexAxis:"y",responsive:true,plugins:{legend:{display:false}},scales:{x:{beginAtZero:true},y:{grid:{display:false},ticks:{font:{size:11}}}}}
  });

  if (chartLinea) chartLinea.destroy();
  chartLinea=new Chart(document.getElementById("chartLinea"),{
    type:"line",
    data:{labels:hist.map(h=>h.fecha),datasets:[{label:"Pacientes",data:hist.map(h=>h.total),borderColor:"#005CA9",backgroundColor:"rgba(0,92,169,.08)",borderWidth:2.5,pointBackgroundColor:"#005CA9",pointRadius:5,fill:true,tension:0.4}]},
    options:{responsive:true,plugins:{legend:{display:false},tooltip:{mode:"index",intersect:false}},scales:{y:{beginAtZero:true},x:{grid:{display:false}}}}
  });

  const maxEps=Math.max(...Object.values(eps),1);
  document.getElementById("tablaEPS").innerHTML=Object.entries(eps).sort((a,b)=>b[1]-a[1]).map(([n,c])=>`
    <tr><td>${n}</td><td><span class="pill pill-azul">${c}</span></td>
    <td style="color:var(--muted);font-family:'DM Mono',monospace;font-size:12px">${total>0?(c/total*100).toFixed(1):0}%</td>
    <td><div class="bar-inline"><div class="bar-inline-fill" style="width:${Math.round(c/maxEps*80)}px"></div></div></td></tr>`).join("")||`<tr><td colspan="4" class="sin-datos">Sin datos</td></tr>`;

  document.getElementById("tablaMedico").innerHTML=Object.entries(medicos).sort((a,b)=>b[1]-a[1]).map(([n,c])=>`
    <tr><td>${n}</td><td><span class="pill pill-verde">${c}</span></td>
    <td style="color:var(--muted);font-family:'DM Mono',monospace;font-size:12px">${total>0?(c/total*100).toFixed(1):0}%</td></tr>`).join("")||`<tr><td colspan="3" class="sin-datos">Sin datos</td></tr>`;

  const maxEsp=Math.max(...espE.map(e=>e[1]),1);
  document.getElementById("tablaEsp").innerHTML=espE.map(([n,c])=>`
    <tr><td>${n}</td><td><span class="pill pill-azul">${c}</span></td>
    <td style="color:var(--muted);font-family:'DM Mono',monospace;font-size:12px">${total>0?(c/total*100).toFixed(1):0}%</td>
    <td><div class="bar-inline"><div class="bar-inline-fill" style="background:var(--verde);width:${Math.round(c/maxEsp*120)}px"></div></div></td></tr>`).join("")||`<tr><td colspan="4" class="sin-datos">Sin datos</td></tr>`;

  document.getElementById("footerTs").textContent=`Generado automáticamente por Bot RPA SEMFU · Actualizado: ${new Date().toLocaleString("es-CO")}`;
}

window.addEventListener("DOMContentLoaded",()=>aplicarAtajo(7,document.querySelector(".atajo-btn")));
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════
# GITHUB PAGES — Subir dashboard y obtener link
# ══════════════════════════════════════════════════════
def subir_dashboard_a_github(ruta_html, nombre_hoja):
    """Sube el dashboard HTML a GitHub Pages y retorna el link público."""
    log("Subiendo dashboard a GitHub Pages...")

    with open(ruta_html, "r", encoding="utf-8") as f:
        contenido = f.read()

    auth = Auth.Token(GITHUB_TOKEN)
    g    = Github(auth=auth)
    repo = g.get_repo(GITHUB_REPO)

    nombre_archivo = f"dashboard_{nombre_hoja}.html"
    commit_msg = f"Dashboard SEMFU — {nombre_hoja}"

    try:
        archivo = repo.get_contents(nombre_archivo)
        repo.update_file(nombre_archivo, commit_msg, contenido, archivo.sha)
        log(f"Archivo '{nombre_archivo}' actualizado ✓")
    except Exception:
        repo.create_file(nombre_archivo, commit_msg, contenido)
        log(f"Archivo '{nombre_archivo}' creado ✓")

    try:
        index = repo.get_contents("index.html")
        repo.update_file("index.html", commit_msg, contenido, index.sha)
    except Exception:
        repo.create_file("index.html", commit_msg, contenido)
    log("index.html actualizado ✓")

    link = f"{GITHUB_PAGES_URL}/index.html"
    log(f"Link GitHub Pages: {link} ✓")
    return link

# ══════════════════════════════════════════════════════
# CORREO CON LINK AL DASHBOARD
# ══════════════════════════════════════════════════════
def enviar_correo(total, nombre_hoja, conteos_eps, link_dashboard=None, exito=True, error_msg=None):
    log("Enviando correo...")

    if exito:
        asunto = f"✅ Reporte SISMA — {nombre_hoja} — {total} pacientes"
        detalle_eps = "".join([
            f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee'>{eps}</td>"
            f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:center'><b>{count}</b></td></tr>"
            for eps, count in conteos_eps.items()
        ]) or "<tr><td colspan='2' style='padding:6px 12px;color:#888'>Sin detalle</td></tr>"

        boton_dashboard = (
            f'<a href="{link_dashboard}" style="display:inline-block;background:#8CC63F;color:white;'
            f'padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;'
            f'margin-top:8px;margin-right:8px">📊 Ver Dashboard →</a>'
        ) if link_dashboard else ""

        cuerpo = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:0 auto">
          <div style="background:linear-gradient(135deg,#005CA9,#00A8E0);padding:24px 28px;border-radius:10px 10px 0 0">
            <h2 style="color:white;margin:0">📋 Reporte Diario SISMA</h2>
            <p style="color:#cce0ff;margin:4px 0 0">Fundación Sembrando Futuro — SEMFU</p>
          </div>
          <div style="background:#f9f9f9;padding:24px 28px;border-radius:0 0 10px 10px;border:1px solid #ddd">
            <p>El bot ejecutó el proceso exitosamente el día <b>{nombre_hoja}</b>.</p>
            <div style="background:white;border-radius:8px;padding:20px;margin:16px 0;border:1px solid #eee;text-align:center">
              <div style="font-size:48px;font-weight:700;color:#1D9E75">{total}</div>
              <div style="color:#888;margin-top:4px">pacientes atendidos registrados</div>
            </div>
            <div style="background:white;border-radius:8px;padding:16px;margin:16px 0;border:1px solid #eee">
              <b style="color:#005CA9">Por EPS / Contrato</b>
              <table style="width:100%;border-collapse:collapse;margin-top:10px">
                <tr style="background:#f0f5ff">
                  <th style="padding:6px 12px;text-align:left;font-size:13px">Contrato</th>
                  <th style="padding:6px 12px;text-align:center;font-size:13px">Pacientes</th>
                </tr>
                {detalle_eps}
              </table>
            </div>
            {boton_dashboard}
            <a href="{SHEET_URL}" style="display:inline-block;background:#005CA9;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;margin-top:8px">
              Ver en Google Sheets →
            </a>
            <p style="color:#bbb;font-size:11px;margin-top:20px">
              Generado automáticamente por Bot RPA SEMFU · {fecha_hoy()}
            </p>
          </div>
        </body></html>"""
    else:
        asunto = f"❌ Error en Bot SISMA — {nombre_hoja}"
        cuerpo = f"""
        <html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:0 auto">
          <div style="background:#c0392b;padding:24px 28px;border-radius:10px 10px 0 0">
            <h2 style="color:white;margin:0">⚠️ Error en Bot SISMA</h2>
            <p style="color:#fdd;margin:4px 0 0">Fundación Sembrando Futuro — SEMFU</p>
          </div>
          <div style="background:#f9f9f9;padding:24px 28px;border-radius:0 0 10px 10px;border:1px solid #ddd">
            <p>El bot encontró un error el día <b>{nombre_hoja}</b>.</p>
            <div style="background:#fff5f5;border-left:4px solid #c0392b;padding:12px 16px;border-radius:4px;font-family:monospace;font-size:13px">
              {error_msg}
            </div>
            <p style="margin-top:16px">Por favor ejecuta el proceso manualmente en SISMA.</p>
          </div>
        </body></html>"""

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = asunto
        msg["From"]    = EMAIL_REMITENTE
        msg["To"]      = EMAIL_DESTINATARIO

        alternativa = MIMEMultipart("alternative")
        alternativa.attach(MIMEText(cuerpo, "html"))
        msg.attach(alternativa)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
            servidor.login(EMAIL_REMITENTE, EMAIL_CONTRASENA)
            servidor.sendmail(EMAIL_REMITENTE, EMAIL_DESTINATARIO, msg.as_string())

        log(f"Correo enviado a {EMAIL_DESTINATARIO} ✓")
    except Exception as e:
        log(f"⚠ No se pudo enviar el correo: {e}")

# ══════════════════════════════════════════════════════
# MODO TEST
# ══════════════════════════════════════════════════════
def modo_test(fecha=None):
    log("════════════════════════════════════════")
    log("  MODO TEST — sin abrir SISMA")
    log("════════════════════════════════════════")

    nombre_hoja = fecha if fecha else nombre_hoja_hoy()
    log(f"Escribiendo en hoja: '{nombre_hoja}'")

    encabezados_falsos = ["No.", "TIPO IDENT.", "PACIENTE", "SEXO", "FECHA NACIMIENTO", "CONTRATO"]
    datos_falsos = [
        ["1", "RC", "PACIENTE TEST UNO",   "F", "2000-01-15", "CONTRATO NEUROSER SUBSIDIADO PGP"],
        ["2", "TI", "PACIENTE TEST DOS",   "M", "1995-06-20", "CONTRATO ACTIVAMENTE"],
        ["3", "RC", "PACIENTE TEST TRES",  "F", "1988-03-10", "CONTRATO NEUROSER SUBSIDIADO PGP"],
        ["4", "RC", "PACIENTE TEST CUATRO","M", "2001-11-05", "CONTRATO ACTIVAMENTE"],
        ["5", "TI", "PACIENTE TEST CINCO", "F", "1990-07-22", "CONTRATO NEUROSER SUBSIDIADO PGP"],
    ]

    total    = exportar_a_sheets(encabezados_falsos, datos_falsos, nombre_hoja)
    conteos  = analizar_datos(encabezados_falsos, datos_falsos)
    historial = obtener_historial_dashboard()
    ruta      = generar_dashboard_html(nombre_hoja, total, conteos, historial)
    link      = subir_dashboard_a_github(ruta, nombre_hoja)
    enviar_correo(total, nombre_hoja, conteos, link_dashboard=link, exito=True)
    log("✅ Test completado — revisa Gmail, el correo trae el link al dashboard")

# ══════════════════════════════════════════════════════
# HELPERS DE FECHA
# ══════════════════════════════════════════════════════
def ddmmyyyy_a_sisma(fecha_ddmmyyyy):
    """Convierte DD-MM-YYYY → YYYY/MM/DD (formato que usa SISMA en la URL)."""
    partes = fecha_ddmmyyyy.split("-")
    return f"{partes[2]}/{partes[1]}/{partes[0]}"

def validar_fecha(fecha_str):
    """Valida que el string tenga formato DD-MM-YYYY. Lanza ValueError si no."""
    try:
        datetime.datetime.strptime(fecha_str, "%d-%m-%Y")
    except ValueError:
        raise ValueError(f"Formato de fecha inválido: '{fecha_str}'. Debe ser DD-MM-YYYY.")

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    # ── Modo TEST ──────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        fecha = sys.argv[2] if len(sys.argv) > 2 else None
        modo_test(fecha)
        return

    log("═══════════════════════════════════════")
    log("  BOT SISMA → Google Sheets — SEMFU")
    log("═══════════════════════════════════════")

    # ── Fecha: argumento o hoy ─────────────────────────
    if len(sys.argv) > 1:
        nombre_hoja = sys.argv[1]          # DD-MM-YYYY pasado por argumento
        try:
            validar_fecha(nombre_hoja)
        except ValueError as e:
            log(f"❌ {e}")
            sys.exit(1)
        fecha_sisma = ddmmyyyy_a_sisma(nombre_hoja)
        log(f"Fecha solicitada: {nombre_hoja} (SISMA: {fecha_sisma})")
    else:
        nombre_hoja = nombre_hoja_hoy()    # fecha de hoy por defecto
        fecha_sisma = fecha_hoy()
        log(f"Fecha: hoy ({nombre_hoja})")

    driver = None

    try:
        driver = iniciar_driver()
        login(driver)
        ir_a_consolidados(driver)
        generar_informe(driver, fecha_sisma)   # ← pasa la fecha al reporte
        encabezados, datos = extraer_datos(driver)

        if datos:
            total     = exportar_a_sheets(encabezados, datos, nombre_hoja)
            conteos   = analizar_datos(encabezados, datos)
            historial = obtener_historial_dashboard()
            ruta      = generar_dashboard_html(nombre_hoja, total, conteos, historial)
            link      = subir_dashboard_a_github(ruta, nombre_hoja)
            enviar_correo(total, nombre_hoja, conteos, link_dashboard=link, exito=True)
        else:
            log(f"⚠ Sin datos para {nombre_hoja}")
            enviar_correo(0, nombre_hoja, {}, exito=True)

        log("Proceso finalizado ✓")

    except Exception as e:
        log(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        enviar_correo(0, nombre_hoja, {}, exito=False, error_msg=str(e))
    finally:
        if driver:
            time.sleep(3)
            driver.quit()
            log("Navegador cerrado")

if __name__ == "__main__":
    main()
