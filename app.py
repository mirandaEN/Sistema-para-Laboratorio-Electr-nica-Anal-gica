from dotenv import load_dotenv
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_file
import cx_Oracle
import re
import traceback 
import json
from datetime import datetime, time, timedelta
import pandas as pd
import io

load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey" 

# --- CONSTANTES DE SEGURIDAD ---
LOCK_MAX_ATTEMPTS = 3
LOCK_TIME_MIN = 5

# Configuración del cliente de Oracle
cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# --- CONEXIÓN A LA BASE DE DATOS ---
db_user = 'JEFE_LAB'
db_password = 'jefe123' 
dsn = 'localhost:1521/XEPDB1'

def get_db_connection():
    try:
        return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
    except cx_Oracle.DatabaseError as e:
        print(f"--- ERROR DE CONEXIÓN A ORACLE: {e} ---")
        traceback.print_exc()
        return None

def rows_to_dicts(cursor, rows):
    column_names = [d[0].upper() for d in cursor.description]
    results = []
    for row in rows:
        row_dict = dict(zip(column_names, row))
        cleaned_dict = {}
        for key, value in row_dict.items():
            if isinstance(value, (datetime, cx_Oracle.Timestamp, timedelta)):
                cleaned_dict[key] = str(value)
            elif isinstance(value, cx_Oracle.LOB):
                cleaned_dict[key] = value.read()
            elif value is None:
                cleaned_dict[key] = None
            else:
                cleaned_dict[key] = value
        results.append(cleaned_dict)
    return results

# --- FUNCIONES DE AUTENTICACIÓN ---
def autenticar_con_bloqueo(usuario, contrasena):
    conn = get_db_connection()
    if not conn: return (False, None, "Error de conexión con la base de datos.")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, USUARIO, PASSWORD, TIPO, CREADO_EN, INTENTOS_FALLIDOS, BLOQUEADO_HASTA FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        row = cursor.fetchone()
        if not row:
            return (False, None, "Usuario o contraseña incorrectos.")
        
        id_db, user_db, pwd_db, tipo_db, creado_en_db, intentos_db, bloqueado_hasta_db = row

        if bloqueado_hasta_db is not None and bloqueado_hasta_db > datetime.now():
            cursor.execute("SELECT CEIL((CAST(BLOQUEADO_HASTA AS DATE) - CAST(SYSDATE AS DATE)) * 24 * 60) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
            mins_left = cursor.fetchone()[0]
            return (False, None, f"Cuenta bloqueada. Intenta de nuevo en {int(mins_left) if mins_left and mins_left > 0 else 1} minuto(s).")
        
        if contrasena == pwd_db:
            cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = 0, BLOQUEADO_HASTA = NULL WHERE USUARIO = :usr", usr=usuario)
            conn.commit()
            return (True, {'id': id_db, 'nombre': user_db, 'tipo': tipo_db}, "Acceso concedido.")
        else:
            nuevos_intentos = intentos_db + 1
            if nuevos_intentos >= LOCK_MAX_ATTEMPTS:
                cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = :i, BLOQUEADO_HASTA = SYSTIMESTAMP + NUMTODSINTERVAL(:m, 'MINUTE') WHERE USUARIO = :usr", i=nuevos_intentos, m=LOCK_TIME_MIN, usr=usuario)
                msg = f"Usuario o contraseña incorrectos. La cuenta ha sido bloqueada."
            else:
                cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = :i WHERE USUARIO = :usr", i=nuevos_intentos, usr=usuario)
                msg = f"Usuario o contraseña incorrectos. Te quedan {LOCK_MAX_ATTEMPTS - nuevos_intentos} intento(s)."
            conn.commit()
            return (False, None, msg)
    except Exception as e:
        print(f"Error Oracle en autenticar_con_bloqueo: {e}"); traceback.print_exc()
        return (False, None, "Error de base de datos. Revisa la consola de Flask.")
    finally:
        if conn: conn.close() 

# --- RUTAS PRINCIPALES ---
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()
        if not usuario or not contrasena:
            flash("Ambos campos son obligatorios.", "danger"); return redirect(url_for('login'))
        es_valido, datos_usuario, mensaje = autenticar_con_bloqueo(usuario, contrasena)
        if es_valido:
            session['user_id'] = datos_usuario['id']
            session['user_rol'] = 'admin' if datos_usuario['tipo'] == 0 else 'auxiliar'
            session['user_nombre'] = datos_usuario['nombre']
            if session.get('user_rol') == 'auxiliar':
                conn = get_db_connection()
                if conn:
                    try:
                        cursor = conn.cursor()
                        cursor.execute("INSERT INTO REGISTRO_ACTIVIDAD (ID, ID_USUARIO, TIPO_ACCION) VALUES (registro_actividad_seq.nextval, :id_usr, 'INICIO_SESION')", id_usr=session['user_id'])
                        conn.commit()
                    except Exception as e: print(f"Error al registrar actividad: {e}")
                    finally: 
                        if 'cursor' in locals() and cursor: cursor.close()
                        if conn: conn.close()
            if datos_usuario['tipo'] == 0: return redirect(url_for("interface_admin"))
            else: return redirect(url_for("interface_aux"))
        else:
            flash(mensaje, "danger")
            return redirect(url_for('login'))
    return render_template("inicioAdmin.html")

@app.route('/logout')
def logout():
    alerta_guillermo = None
    if session.get('user_rol') == 'auxiliar' and session.get('user_id'):
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                prestamos_pendientes = 0
                if session.get('user_nombre') == 'Guillermo Alvarez': 
                    cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE ID_AUXILIAR = :id_aux AND ESTATUS = 'Activo'", id_aux=session['user_id'])
                    prestamos_pendientes = cursor.fetchone()[0]
                    if prestamos_pendientes > 0:
                        alerta_guillermo = f"¡Alerta, Guillermo! Has cerrado sesión con {prestamos_pendientes} préstamo(s) activo(s)."
                
                cursor.execute("INSERT INTO REGISTRO_ACTIVIDAD (ID, ID_USUARIO, TIPO_ACCION, PRESTAMOS_PENDIENTES) VALUES (registro_actividad_seq.nextval, :id_usr, 'CIERRE_SESION', :pendientes)", id_usr=session['user_id'], pendientes=prestamos_pendientes)
                conn.commit()
            except Exception as e: print(f"Error durante el logout: {e}")
            finally:
                if 'cursor' in locals() and cursor: cursor.close()
                if conn: conn.close()
    session.clear()
    if alerta_guillermo:
        flash(alerta_guillermo, "warning")
    flash("Has cerrado sesión exitosamente.", "success")
    return redirect(url_for('login'))

# --- RUTAS DE NAVEGACIÓN ---
@app.route("/interface_admin")
def interface_admin(): return render_template("interfaceAdmin.html")

@app.route("/interface_aux")
def interface_aux(): return render_template("interfaceAux.html")

# --- RUTA DE SOPORTE TÉCNICO ---
@app.route('/soporte', methods=['GET', 'POST'])
def soporte():
    if request.method == 'POST':
        nombre = request.form.get('name', '').strip()
        correo_remitente = request.form.get('email', '').strip()
        asunto = request.form.get('subject', '').strip()
        mensaje = request.form.get('message', '').strip()
        if not all([nombre, correo_remitente, asunto, mensaje]):
            flash("Todos los campos son obligatorios.", "danger")
            return render_template('soporte.html')
        guardado_ok, error_db = guardar_mensaje_soporte_db(nombre, correo_remitente, asunto, mensaje)
        if guardado_ok:
            envio_ok, error_correo = enviar_notificacion_sendgrid(nombre, correo_remitente, asunto, mensaje)
            if envio_ok:
                flash("Tu mensaje ha sido enviado con éxito. Te contactaremos pronto.", "success")
            else:
                print(f"--- ERROR AL ENVIAR CORREO CON SENDGRID: {error_correo} ---")
                flash("Tu mensaje fue registrado, pero hubo un error al enviar la notificación. Contacta a un administrador.", "warning")
        else:
            flash(f"Error al registrar el mensaje: {error_db}", "danger")
        return redirect(url_for('soporte'))
    return render_template('soporte.html')

# --- FUNCIONES DE AYUDA DE SOPORTE ---
def enviar_notificacion_sendgrid(nombre, correo_remitente, asunto, mensaje):
    SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
    if not SENDGRID_API_KEY:
        print("--- ERROR: La variable de entorno SENDGRID_API_KEY no está configurada. ---")
        return False, "El servicio de correo no está configurado."
    from_email = 'mirandaneyra1@gmail.com' 
    to_email = 'mirandaneyra1@gmail.com' 
    html_content = f"""<h3>Has recibido un nuevo mensaje de soporte:</h3><p><strong>De:</strong> {nombre} ({correo_remitente})</p><p><strong>Asunto:</strong> {asunto}</p><hr><p><strong>Mensaje:</strong></p><p>{mensaje.replace(chr(10), '<br>')}</p><hr><p><small>Este mensaje fue enviado desde el formulario de soporte del sistema de laboratorio.</small></p>"""
    message = Mail(from_email=from_email, to_emails=to_email, subject=f"Nuevo Mensaje de Soporte: {asunto}", html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        if 200 <= response.status_code < 300: return True, None
        else:
            print(f"--- ERROR: SendGrid devolvió un error. Código: {response.status_code}, Body: {response.body} ---")
            return False, response.body
    except Exception as e:
        traceback.print_exc()
        return False, str(e)

def guardar_mensaje_soporte_db(nombre, correo, asunto, mensaje):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO MENSAJES_SOPORTE (NOMBRE_REMITENTE, CORREO_REMITENTE, ASUNTO, MENSAJE) VALUES (:nombre, :correo, :asunto, :mensaje)",
                       nombre=nombre, correo=correo, asunto=asunto, mensaje=mensaje)
        conn.commit()
        return True, None
    except Exception as e:
        conn.rollback(); print(f"Error Oracle en guardar_mensaje_soporte_db: {e}"); traceback.print_exc()
        return False, "Ocurrió un error interno."
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()

# --- RUTA DE REPORTES AVANZADA ---
@app.route('/reportes')
def reportes():
    if 'user_rol' not in session or session['user_rol'] != 'admin':
        flash('Acceso no autorizado.', 'danger'); return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return render_template('reportes.html', datos={}, usuario_rol=session.get('user_rol'))
    
    datos_dashboard = {}
    try:
        cursor = conn.cursor()
        
        # --- KPIs ---
        cursor.execute("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL NOT IN (SELECT DISTINCT ID_MATERIAL FROM DETALLE_PRESTAMO)"); datos_dashboard['stock_muerto'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(rd.CANTIDAD_DANADA) AS TOTAL_DANADO FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL_DANADO DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_danos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.SEMESTRE, COUNT(p.ID_PRESTAMO) AS TOTAL_PRESTAMOS FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO GROUP BY a.SEMESTRE ORDER BY TOTAL_PRESTAMOS DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_semestres'] = rows_to_dicts(cursor, cursor.fetchall())
        query_prestamos_hora = "SELECT TO_CHAR(p.FECHA_HORA, 'HH24') AS HORA, COUNT(*) AS TOTAL, LISTAGG(DISTINCT u.USUARIO, ', ') WITHIN GROUP (ORDER BY u.USUARIO) AS AUXILIARES FROM PRESTAMOS p JOIN USUARIOS u ON p.ID_AUXILIAR = u.ID WHERE p.FECHA_HORA >= TRUNC(SYSDATE) GROUP BY TO_CHAR(p.FECHA_HORA, 'HH24') ORDER BY HORA"
        cursor.execute(query_prestamos_hora); datos_dashboard['prestamos_por_hora'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND (SYSTIMESTAMP - p.FECHA_HORA) > INTERVAL '1' HOUR ORDER BY p.FECHA_HORA ASC"); datos_dashboard['prestamos_vencidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT ROUND(AVG( (CAST(FECHA_DEVOLUCION AS DATE) - CAST(FECHA_HORA AS DATE)) * 24 * 60 )) FROM PRESTAMOS WHERE ESTATUS = 'Devuelto' AND FECHA_DEVOLUCION IS NOT NULL"); avg_time = cursor.fetchone()[0]; datos_dashboard['tiempo_promedio_prestamo'] = avg_time if avg_time else 0
        cursor.execute("SELECT USUARIO, INTENTOS_FALLIDOS FROM USUARIOS WHERE TIPO = 1 AND INTENTOS_FALLIDOS > 0 ORDER BY INTENTOS_FALLIDOS DESC"); datos_dashboard['logins_fallidos'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_materiales_pedidos'] = rows_to_dicts(cursor, cursor.fetchall())

    except Exception as e:
        flash(f"Error al generar reportes avanzados: {e}", "danger")
        traceback.print_exc()
    finally:
        if conn:
            if 'cursor' in locals() and cursor: cursor.close()
            conn.close()
            
    return render_template('reportes.html', datos=datos_dashboard, usuario_rol=session.get('user_rol'))

# --- RUTA PARA DESCARGAR REPORTE EN EXCEL ---
@app.route('/descargar_reporte_excel')
def descargar_reporte_excel():
    if session.get('user_rol') != 'admin':
        return "Acceso no autorizado.", 403

    conn = get_db_connection()
    if not conn:
        flash("Error de conexión para generar el reporte.", "danger")
        return redirect(url_for('reportes'))

    try:
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')

        pd.read_sql("SELECT a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND (SYSTIMESTAMP - p.FECHA_HORA) > INTERVAL '1' HOUR ORDER BY p.FECHA_HORA ASC", conn).to_excel(writer, sheet_name='Prestamos Vencidos', index=False)
        pd.read_sql("SELECT m.NOMBRE, SUM(rd.CANTIDAD_DANADA) AS TOTAL_DANADO FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL_DANADO DESC", conn).to_excel(writer, sheet_name='Materiales Mas Danados', index=False)
        pd.read_sql("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY", conn).to_excel(writer, sheet_name='Top Materiales Pedidos', index=False)
        pd.read_sql("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL NOT IN (SELECT DISTINCT ID_MATERIAL FROM DETALLE_PRESTAMO)", conn).to_excel(writer, sheet_name='Stock Muerto', index=False)
        pd.read_sql("SELECT a.SEMESTRE, COUNT(p.ID_PRESTAMO) AS TOTAL_PRESTAMOS FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO GROUP BY a.SEMESTRE ORDER BY TOTAL_PRESTAMOS DESC", conn).to_excel(writer, sheet_name='Uso por Semestre', index=False)
        pd.read_sql("SELECT USUARIO, INTENTOS_FALLIDOS FROM USUARIOS WHERE TIPO = 1 AND INTENTOS_FALLIDOS > 0 ORDER BY INTENTOS_FALLIDOS DESC", conn).to_excel(writer, sheet_name='Logins Fallidos Auxiliares', index=False)
        
        writer.close()
        output.seek(0)

        return send_file(output, download_name='Reporte_Laboratorio.xlsx', as_attachment=True)

    except Exception as e:
        flash(f"Error al generar el archivo Excel: {e}", "danger")
        traceback.print_exc()
        return redirect(url_for('reportes'))
    finally:
        if conn: conn.close()

# --- RUTAS Y FUNCIONES DE GESTIÓN DE AUXILIARES ---
@app.route('/gestion_auxiliares')
def gestion_auxiliares():
    if session.get('user_rol') != 'admin':
        flash("Acceso no autorizado.", "danger"); return redirect(url_for('login'))
    auxiliares = obtener_auxiliares_db()
    return render_template('gestion_auxiliares.html', auxiliares=auxiliares)

@app.route('/agregar_auxiliar', methods=['POST'])
def agregar_auxiliar():
    if session.get('user_rol') != 'admin': return redirect(url_for('login'))
    usuario = request.form.get('usuario', '').strip()
    contrasena = request.form.get('contrasena', '').strip()
    if not usuario or not contrasena:
        flash("Usuario y contraseña son obligatorios.", "warning"); return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = insertar_auxiliar_db(usuario, contrasena)
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/modificar_auxiliar', methods=['POST'])
def modificar_auxiliar():
    if session.get('user_rol') != 'admin': return redirect(url_for('login'))
    id_usuario = request.form.get('id_usuario'); usuario = request.form.get('usuario', '').strip(); contrasena = request.form.get('contrasena', '').strip()
    if not id_usuario or not usuario:
        flash("Faltan datos para modificar.", "danger"); return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = actualizar_auxiliar_db(id_usuario, usuario, contrasena)
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

@app.route('/eliminar_auxiliar', methods=['POST'])
def eliminar_auxiliar():
    if session.get('user_rol') != 'admin': return redirect(url_for('login'))
    id_usuario = request.form.get('id_usuario')
    if not id_usuario:
        flash("No se especificó ID para eliminar.", "danger"); return redirect(url_for('gestion_auxiliares'))
    resultado, mensaje = eliminar_auxiliar_db(id_usuario)
    flash(mensaje, "success" if resultado else "danger"); return redirect(url_for('gestion_auxiliares'))

# --- RUTA PARA REINICIAR EL SISTEMA ---
@app.route('/reiniciar_sistema', methods=['POST'])
def reiniciar_sistema():
    if session.get('user_rol') != 'admin':
        flash("Acción no autorizada.", "danger")
        return redirect(url_for('login'))
    
    confirmacion = request.form.get('confirmacion')
    if confirmacion != 'REINICIAR':
        flash("La palabra de confirmación es incorrecta. No se ha realizado ninguna acción.", "warning")
        return redirect(url_for('gestion_auxiliares'))

    resultado, mensaje = reiniciar_registros_db()
    flash(mensaje, "success" if resultado else "danger")
    return redirect(url_for('gestion_auxiliares'))

def obtener_auxiliares_db():
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID, USUARIO FROM USUARIOS WHERE TIPO = 1 ORDER BY USUARIO")
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e: print(f"Error al obtener auxiliares: {e}"); return []
    finally:
        if conn: cursor.close(); conn.close()

def insertar_auxiliar_db(usuario, contrasena):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        if cursor.fetchone()[0] > 0: return False, f"El usuario '{usuario}' ya existe."
        cursor.execute("INSERT INTO USUARIOS (USUARIO, PASSWORD, TIPO) VALUES (:usr, :pwd, 1)", usr=usuario, pwd=contrasena)
        conn.commit(); return True, f"Auxiliar '{usuario}' agregado."
    except Exception as e:
        conn.rollback(); print(f"Error al insertar auxiliar: {e}"); return False, "Error interno al agregar."
    finally:
        if conn: cursor.close(); conn.close()

def actualizar_auxiliar_db(id_usuario, usuario, contrasena):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM USUARIOS WHERE USUARIO = :usr AND ID != :id_usr", usr=usuario, id_usr=id_usuario)
        if cursor.fetchone()[0] > 0: return False, f"El nombre '{usuario}' ya está en uso."
        if contrasena:
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr, PASSWORD = :pwd WHERE ID = :id_usr", usr=usuario, pwd=contrasena, id_usr=id_usuario)
        else:
            cursor.execute("UPDATE USUARIOS SET USUARIO = :usr WHERE ID = :id_usr", usr=usuario, id_usr=id_usuario)
        conn.commit()
        return (True, "Auxiliar actualizado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except Exception as e:
        conn.rollback(); print(f"Error al actualizar auxiliar: {e}"); return False, "Error interno al actualizar."
    finally:
        if conn: cursor.close(); conn.close()

def eliminar_auxiliar_db(id_usuario):
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM USUARIOS WHERE ID = :id_usr AND TIPO = 1", id_usr=id_usuario)
        conn.commit()
        return (True, "Auxiliar eliminado.") if cursor.rowcount > 0 else (False, "No se encontró el auxiliar.")
    except cx_Oracle.IntegrityError:
        conn.rollback(); return False, "No se puede eliminar, tiene registros asociados (préstamos, etc.)."
    except Exception as e:
        conn.rollback(); print(f"Error al eliminar auxiliar: {e}"); return False, "Error interno al eliminar."
    finally:
        if conn: cursor.close(); conn.close()

# --- FUNCIÓN DE AYUDA PARA REINICIAR REGISTROS ---
def reiniciar_registros_db():
    conn = get_db_connection()
    if not conn: return False, "Error de conexión."
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM DETALLE_PRESTAMO")
        cursor.execute("DELETE FROM REGISTRO_DANOS")
        cursor.execute("DELETE FROM PRESTAMOS")
        cursor.execute("DELETE FROM REGISTRO_ACTIVIDAD")
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD, CANTIDAD_DANADA = 0")
        conn.commit()
        return True, "El sistema ha sido reiniciado. Todos los préstamos, daños y registros de actividad han sido eliminados."
    except Exception as e:
        conn.rollback()
        print(f"Error al reiniciar el sistema: {e}"); traceback.print_exc()
        return False, "Ocurrió un error interno al intentar reiniciar el sistema."
    finally:
        if conn: cursor.close(); conn.close()

# --- RUTAS Y FUNCIONES DE ALUMNOS ---
@app.route("/registro_alumno", methods=["GET", "POST"])
def registro_alumno():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        numero_control = request.form.get("numero_control", "").strip()
        correo = request.form.get("correo", "").strip()
        especialidad = request.form.get("carrera", "").strip()
        semestre = request.form.get("semestre", "").strip()
        if not all([nombre, numero_control, correo, especialidad, semestre]):
            flash("Completa todos los campos.", "warning"); return render_template("inicioAlumno.html")
        resultado = registrar_alumno_db(nombre, numero_control, correo, especialidad, int(semestre))
        if resultado == "duplicado": flash("El número de control o correo ya están registrados.", "error")
        elif resultado == "ok": flash("Te has registrado con éxito.", "success")
        else: flash("Error al registrar alumno. Intenta de nuevo.", "error")
    return render_template("inicioAlumno.html")

def registrar_alumno_db(nombre, numero_control, correo, especialidad, semestre):
    conn = get_db_connection()
    if not conn: return "error"
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM ALUMNOS WHERE NUMEROCONTROL = :nc OR CORREO = :cr", nc=numero_control, cr=correo)
        if cursor.fetchone()[0] > 0: return "duplicado"
        cursor.execute("INSERT INTO ALUMNOS (nombre, numerocontrol, correo, especialidad, semestre) VALUES (:n, :nc, :cr, :e, :s)", n=nombre, nc=numero_control, cr=correo, e=especialidad, s=semestre)
        conn.commit()
        return "ok"
    except Exception as e: print(f"Error Oracle en registrar_alumno: {e}"); conn.rollback(); return "error"
    finally:
        if conn: cursor.close(); conn.close()

# --- RUTAS Y FUNCIONES DE INVENTARIO ---
@app.route('/inventario')
def inventario():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('inventario.html', materiales=obtener_materiales(), usuario_rol=session.get('user_rol'))

def obtener_materiales():
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD AS CANTIDAD_TOTAL, CANTIDAD_DISPONIBLE, CANTIDAD_DANADA,
                   (CANTIDAD - CANTIDAD_DISPONIBLE - CANTIDAD_DANADA) AS CANTIDAD_EN_USO,
                   CASE WHEN CANTIDAD_DISPONIBLE = 0 THEN 'Sin stock' WHEN (CANTIDAD - CANTIDAD_DISPONIBLE - CANTIDAD_DANADA) > 0 THEN 'En uso' ELSE 'Disponible' END AS ESTATUS
            FROM MATERIALES ORDER BY ID_MATERIAL
        """)
        return rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e:
        print(f"Error al obtener_materiales: {e}"); flash(f"Error al cargar inventario: {str(e).splitlines()[0]}", 'danger'); return []
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/agregar_material', methods=['POST'])
def agregar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    if not nombre or not cantidad:
        flash('Nombre y Cantidad son obligatorios.', 'danger'); return redirect(url_for('inventario'))
    try:
        cantidad_int = int(cantidad)
        if cantidad_int <= 0: raise ValueError
    except ValueError:
        flash('La cantidad debe ser un número entero positivo.', 'danger'); return redirect(url_for('inventario'))
    nuevo_id, resultado = insertar_material(nombre, tipo, marca_modelo, cantidad_int)
    if resultado == "ok": flash(f'Material "{nombre}" agregado (ID: {nuevo_id}).', 'success')
    else: flash(f'Error al agregar material: {resultado}', 'danger')
    return redirect(url_for('inventario'))

def insertar_material(nombre, tipo, marca_modelo, cantidad):
    conn = get_db_connection()
    if not conn: return None, "error: sin conexión"
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT NVL(MAX(ID_MATERIAL), 0) + 1 FROM MATERIALES")
        nuevo_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO MATERIALES (ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, CANTIDAD_DISPONIBLE, CANTIDAD_DANADA) VALUES (:id, :n, :t, :m, :c, :cd, 0)", id=nuevo_id, n=nombre, t=tipo, m=marca_modelo, c=cantidad, cd=cantidad)
        conn.commit()
        return nuevo_id, "ok"
    except Exception as e: conn.rollback(); error_msg = str(e).splitlines()[0]; print(f"Error Oracle al insertar_material: {error_msg}"); return None, f"error: {error_msg}"
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/modificar_material', methods=['POST'])
def modificar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_material = int(request.form.get('id_material'))
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = int(request.form.get('cantidad'))
    if actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad): flash(f'Material ID {id_material} modificado.', 'warning')
    else: flash(f'Error: No se pudo actualizar el material ID {id_material}.', 'danger')
    return redirect(url_for('inventario'))

def actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad):
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT CANTIDAD, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL = :id", id=id_material)
        material_actual = cursor.fetchone()
        if not material_actual: return False
        
        diferencia = cantidad - material_actual[0]
        nueva_cantidad_disponible = material_actual[1] + diferencia
        
        if nueva_cantidad_disponible < 0: return False
            
        cursor.execute("UPDATE MATERIALES SET NOMBRE = :n, TIPO = :t, MARCA_MODELO = :m, CANTIDAD = :c, CANTIDAD_DISPONIBLE = :cd WHERE ID_MATERIAL = :id", 
                       n=nombre, t=tipo, m=marca_modelo, c=cantidad, cd=nueva_cantidad_disponible, id=id_material)
        conn.commit()
        return cursor.rowcount > 0 
    except Exception as e: conn.rollback(); print(f"Error Oracle al actualizar_material: {e}"); return False
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/eliminar_material', methods=['POST'])
def eliminar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_material = int(request.form.get('id_material'))
    if eliminar_material_db(id_material): flash(f'Material ID {id_material} eliminado.', 'success')
    else: flash(f'Error al eliminar el material ID {id_material}.', 'danger')
    return redirect(url_for('inventario'))

def eliminar_material_db(id_material):
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM MATERIALES WHERE ID_MATERIAL = :id", id=id_material)
        conn.commit()
        return cursor.rowcount > 0 
    except Exception as e: conn.rollback(); print(f"Error Oracle al eliminar_material_db: {e}"); return False
    finally:
        if conn: cursor.close(); conn.close()

# --- RUTAS Y FUNCIONES DE PRÉSTAMOS ---
@app.route('/prestamos')
def prestamos():
    if 'user_id' not in session:
        flash("Por favor, inicia sesión para acceder.", "warning"); return redirect(url_for('login'))
    
    user_context = {'current_user': {'nombre': session.get('user_nombre')}, 'usuario_rol': session.get('user_rol')}
    
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger')
        return render_template('prestamos.html', materiales_disponibles=[], materias=[], maestros=[], prestamos_activos=[], **user_context)
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT ID_MATERIAL, NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE CANTIDAD_DISPONIBLE > 0 ORDER BY NOMBRE")
        materiales_disponibles = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT ID_MATERIA, NOMBRE_MATERIA FROM MATERIAS ORDER BY NOMBRE_MATERIA")
        materias = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT ID_MAESTRO, NOMBRE_COMPLETO FROM MAESTROS ORDER BY NOMBRE_COMPLETO")
        maestros = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT p.ID_PRESTAMO, a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA FROM PRESTAMOS p JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO WHERE p.ESTATUS = 'Activo' AND p.FECHA_HORA >= TRUNC(LOCALTIMESTAMP) ORDER BY p.FECHA_HORA DESC")
        prestamos_activos_base = rows_to_dicts(cursor, cursor.fetchall())
        
        prestamos_con_materiales = []
        for prestamo in prestamos_activos_base:
            fecha_str = prestamo.get('FECHA_HORA')
            if fecha_str:
                try:
                    fecha_objeto = datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S.%f') if '.' in fecha_str else datetime.strptime(fecha_str, '%Y-%m-%d %H:%M:%S')
                    prestamo['FECHA_HORA_DISPLAY'] = fecha_objeto.strftime('%d/%m/%Y %H:%M')
                except ValueError:
                     prestamo['FECHA_HORA_DISPLAY'] = fecha_str 
            else: prestamo['FECHA_HORA_DISPLAY'] = 'N/A'
            cursor.execute("SELECT m.NOMBRE, dp.CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL WHERE dp.ID_PRESTAMO = :id_p", id_p=prestamo['ID_PRESTAMO'])
            materiales_prestados = rows_to_dicts(cursor, cursor.fetchall())
            prestamo['MATERIALES_LISTA'] = ', '.join([f"{m['NOMBRE']} (x{m['CANTIDAD_PRESTADA']})" for m in materiales_prestados])
            prestamos_con_materiales.append(prestamo)

        return render_template('prestamos.html', materiales_disponibles=materiales_disponibles, materias=materias, maestros=maestros, prestamos_activos=prestamos_con_materiales, **user_context)
    except Exception as e:
        error_msg = str(e).splitlines()[0]
        flash(f"Error al cargar préstamos: {error_msg}. Revisa la consola de Flask.", "danger"); traceback.print_exc()
        return render_template('prestamos.html', materiales_disponibles=[], materias=[], maestros=[], prestamos_activos=[], **user_context)
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/api/alumno/<numerocontrol>')
def get_alumno(numerocontrol):
    if 'user_id' not in session: return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Error de base de datos'}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_ALUMNO, NOMBRE, SEMESTRE FROM ALUMNOS WHERE NUMEROCONTROL = :nc", nc=numerocontrol)
        rows = cursor.fetchall()
        if rows: return jsonify(rows_to_dicts(cursor, rows)[0])
        else: return jsonify({'error': 'Alumno no encontrado'}), 404
    except Exception as e: return jsonify({'error': str(e)}), 500
    finally:
        if conn: cursor.close(); conn.close()
        
@app.route('/api/prestamo/<int:id_prestamo>/materiales')
def get_prestamo_materiales(id_prestamo):
    if 'user_id' not in session: return jsonify({'error': 'No autorizado'}), 401
    conn = get_db_connection()
    if not conn: return jsonify({'error': 'Error de base de datos'}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT m.ID_MATERIAL, m.NOMBRE, dp.CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL WHERE dp.ID_PRESTAMO = :id_p AND dp.CANTIDAD_PRESTADA > 0", id_p=id_prestamo)
        materiales = rows_to_dicts(cursor, cursor.fetchall())
        if not materiales: return jsonify({'error': 'No hay materiales activos para reportar daño en este vale.'}), 404
        return jsonify(materiales)
    except Exception as e:
        print(f"Error API get_prestamo_materiales: {e}"); traceback.print_exc()
        return jsonify({'error': 'Error interno al buscar materiales.'}), 500
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/registrar_prestamo', methods=['POST'])
def registrar_prestamo():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        no_control = request.form['no_control']
        materiales_seleccionados = json.loads(request.form.get('materiales_seleccionados', '{}'))
        if not materiales_seleccionados:
            flash('No se seleccionó ningún material.', 'warning'); return redirect(url_for('prestamos'))
        cursor.execute("SELECT ID_ALUMNO FROM ALUMNOS WHERE NUMEROCONTROL = :nc", nc=no_control)
        result = cursor.fetchone()
        if not result:
            flash(f"Alumno con NC {no_control} no encontrado.", "danger"); return redirect(url_for('prestamos'))
        id_alumno = result[0]
        id_prestamo_var = cursor.var(cx_Oracle.NUMBER)
        cursor.execute("INSERT INTO PRESTAMOS (ID_ALUMNO, ID_MATERIA, ID_MAESTRO, ID_AUXILIAR, NUMERO_MESA, ESTATUS, FECHA_HORA) VALUES (:id_a, :id_m, :id_ma, :id_aux, :mesa, 'Activo', LOCALTIMESTAMP) RETURNING ID_PRESTAMO INTO :id_p_out",
                       id_a=id_alumno, id_m=request.form['materia'], id_ma=request.form['maestro'], id_aux=session['user_id'], mesa=request.form.get('mesa'), id_p_out=id_prestamo_var)
        id_nuevo_prestamo = id_prestamo_var.getvalue()[0]
        for id_material, cantidad in materiales_seleccionados.items():
            cursor.execute("INSERT INTO DETALLE_PRESTAMO (ID_PRESTAMO, ID_MATERIAL, CANTIDAD_PRESTADA) VALUES (:p, :m, :c)", p=id_nuevo_prestamo, m=int(id_material), c=int(cantidad))
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE - :c WHERE ID_MATERIAL = :m", c=int(cantidad), m=int(id_material))
        conn.commit()
        flash('Préstamo registrado exitosamente.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar el préstamo: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('prestamos'))

@app.route('/devolver_prestamo', methods=['POST'])
def devolver_prestamo():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_prestamo = request.form.get('id_prestamo')
    if not id_prestamo:
        flash("ID de préstamo no proporcionado.", "danger"); return redirect(url_for('prestamos'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_MATERIAL, CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO WHERE ID_PRESTAMO = :id_p", id_p=int(id_prestamo))
        materiales_a_devolver = rows_to_dicts(cursor, cursor.fetchall())
        for material in materiales_a_devolver:
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :c WHERE ID_MATERIAL = :m", c=material['CANTIDAD_PRESTADA'], m=material['ID_MATERIAL'])
        cursor.execute("UPDATE PRESTAMOS SET ESTATUS = 'Devuelto', FECHA_DEVOLUCION = SYSTIMESTAMP WHERE ID_PRESTAMO = :id_p", id_p=int(id_prestamo))
        conn.commit()
        flash('Material devuelto y stock actualizado.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error en la devolución: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('prestamos'))

@app.route('/registrar_dano', methods=['POST'])
def registrar_dano():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        id_prestamo = int(request.form['id_prestamo']); id_material = int(request.form['id_material']); cantidad_danada = int(request.form['cantidad_danada'])
        motivo = request.form.get('motivo'); id_auxiliar = session['user_id']
        cursor = conn.cursor()
        cursor.execute("INSERT INTO REGISTRO_DANOS (ID_DANO, ID_PRESTAMO, ID_MATERIAL, CANTIDAD_DANADA, MOTIVO, ID_AUXILIAR_REGISTRO) VALUES (REGISTRO_DANOS_SEQ.nextval, :id_p, :id_m, :cant, :motivo, :id_aux)",
                       id_p=id_prestamo, id_m=id_material, cant=cantidad_danada, motivo=motivo, id_aux=id_auxiliar)
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DANADA = CANTIDAD_DANADA + :cant WHERE ID_MATERIAL = :id_m", cant=cantidad_danada, id_m=id_material)
        cursor.execute("UPDATE DETALLE_PRESTAMO SET CANTIDAD_PRESTADA = CANTIDAD_PRESTADA - :cant WHERE ID_PRESTAMO = :id_p AND ID_MATERIAL = :id_m",
                       cant=cantidad_danada, id_p=id_prestamo, id_m=id_material)
        conn.commit()
        flash('Daño registrado correctamente.', 'warning')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar el daño: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('prestamos'))

@app.route('/gestion_danos')
def gestion_danos():
    if 'user_rol' not in session:
        flash("Por favor, inicia sesión.", "warning"); return redirect(url_for('login'))
    usuario_rol = session.get('user_rol')
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return render_template('gestion_danos.html', danos_pendientes=[], usuario_rol=usuario_rol)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rd.ID_DANO, rd.CANTIDAD_DANADA, rd.MOTIVO, rd.FECHA_REGISTRO, rd.ESTATUS_REPOSICION, m.NOMBRE AS NOMBRE_MATERIAL, a.NOMBRE AS NOMBRE_ALUMNO, a.NUMEROCONTROL
            FROM REGISTRO_DANOS rd JOIN MATERIALES m ON rd.ID_MATERIAL = m.ID_MATERIAL JOIN PRESTAMOS p ON rd.ID_PRESTAMO = p.ID_PRESTAMO JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO
            WHERE rd.ESTATUS_REPOSICION = 'PENDIENTE' ORDER BY rd.FECHA_REGISTRO DESC
        """)
        danos_pendientes = rows_to_dicts(cursor, cursor.fetchall())
        return render_template('gestion_danos.html', danos_pendientes=danos_pendientes, usuario_rol=usuario_rol)
    except Exception as e:
        flash(f"Error al cargar daños pendientes: {e}", "danger"); traceback.print_exc()
        return render_template('gestion_danos.html', danos_pendientes=[], usuario_rol=usuario_rol)
    finally:
        if conn: cursor.close(); conn.close()

@app.route('/reponer_dano', methods=['POST'])
def reponer_dano():
    if 'user_rol' not in session: return redirect(url_for('login'))
    id_dano = request.form.get('id_dano')
    if not id_dano:
        flash("ID de daño no proporcionado.", "danger"); return redirect(url_for('gestion_danos'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return redirect(url_for('gestion_danos'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_MATERIAL, CANTIDAD_DANADA FROM REGISTRO_DANOS WHERE ID_DANO = :id_d", id_d=int(id_dano))
        dano = cursor.fetchone()
        if not dano:
            flash(f"Registro de daño ID {id_dano} no encontrado.", "danger"); return redirect(url_for('gestion_danos'))
        id_material, cantidad_danada = dano
        cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :cant, CANTIDAD_DANADA = CANTIDAD_DANADA - :cant WHERE ID_MATERIAL = :id_m",
                       cant=cantidad_danada, id_m=id_material)
        cursor.execute("UPDATE REGISTRO_DANOS SET ESTATUS_REPOSICION = 'REPUESTO' WHERE ID_DANO = :id_d", id_d=int(id_dano))
        conn.commit()
        flash(f'Reposición ID {id_dano} registrada. Se agregaron {cantidad_danada} unidad(es) al stock.', 'success')
    except Exception as e:
        conn.rollback(); flash(f'Error al registrar la reposición: {e}', 'danger'); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('gestion_danos'))

# --- RUTA DE UTILIDAD ---
@app.route('/desbloquear/<nombre_usuario>')
def desbloquear_usuario(nombre_usuario):
    if 'user_rol' not in session or session['user_rol'] != 'admin':
        flash("Acción no permitida.", "danger"); return redirect(url_for('interface_admin'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", "danger"); return redirect(url_for('interface_admin'))
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE USUARIOS SET INTENTOS_FALLIDOS = 0, BLOQUEADO_HASTA = NULL WHERE USUARIO = :usr", usr=nombre_usuario)
        conn.commit()
        if cursor.rowcount > 0: flash(f"Usuario '{nombre_usuario}' desbloqueado.", "success")
        else: flash(f"No se encontró al usuario '{nombre_usuario}'.", "warning")
    except Exception as e: flash(f"Error al desbloquear: {e}", "danger"); conn.rollback()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('interface_admin'))

if __name__ == "__main__":
    app.run(debug=True)

