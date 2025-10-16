from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import cx_Oracle
import re
import traceback 
import json
from datetime import datetime, time

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
    return [dict(zip(column_names, row)) for row in rows]

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

        if bloqueado_hasta_db is not None and bloqueado_hasta_db > cx_Oracle.Timestamp.now():
            cursor.execute("SELECT CEIL((CAST(BLOQUEADO_HASTA AS DATE) - CAST(SYSTIMESTAMP AS DATE)) * 24 * 60) FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
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
        if conn: cursor.close(); conn.close()

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
                    finally: cursor.close(); conn.close()
            if datos_usuario['tipo'] == 0: return redirect(url_for("interface_admin"))
            else: return redirect(url_for("interface_aux"))
        else:
            flash(mensaje, "danger")
            return redirect(url_for('login'))
    return render_template("inicioAdmin.html")

@app.route('/logout')
def logout():
    alerta_guillermo = None
    if session.get('user_rol') == 'auxiliar':
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
                if cursor: cursor.close()
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

# --- RUTA DE REPORTES ---
@app.route('/reportes')
def reportes():
    if 'user_rol' not in session or session['user_rol'] != 'admin':
        flash('Acceso no autorizado.', 'danger'); return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger'); return render_template('reportes.html', datos={})
    datos_dashboard = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM PRESTAMOS WHERE FECHA_HORA >= TRUNC(LOCALTIMESTAMP)"); datos_dashboard['total_prestamos_hoy'] = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(CANTIDAD_DISPONIBLE) FROM MATERIALES"); datos_dashboard['total_stock'] = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM REGISTRO_ACTIVIDAD WHERE TIPO_ACCION = 'INICIO_SESION' AND FECHA_HORA >= TRUNC(LOCALTIMESTAMP)"); datos_dashboard['auxiliares_activos'] = cursor.fetchone()[0]
        
        query_turnos = """
            WITH turnos AS (
                SELECT ID_USUARIO, FECHA_HORA AS INICIO_TURNO,
                       LEAD(FECHA_HORA, 1, LOCALTIMESTAMP + INTERVAL '1' DAY) OVER (ORDER BY FECHA_HORA) AS FIN_TURNO
                FROM REGISTRO_ACTIVIDAD WHERE TIPO_ACCION = 'INICIO_SESION' AND FECHA_HORA >= TRUNC(LOCALTIMESTAMP)
            ) SELECT u.USUARIO, COUNT(p.ID_PRESTAMO) AS PRESTAMOS_EN_TURNO
            FROM turnos t JOIN USUARIOS u ON t.ID_USUARIO = u.ID
            LEFT JOIN PRESTAMOS p ON p.ID_AUXILIAR = t.ID_USUARIO AND p.FECHA_HORA >= t.INICIO_TURNO AND p.FECHA_HORA < t.FIN_TURNO
            WHERE u.TIPO = 1 GROUP BY u.USUARIO ORDER BY MIN(t.INICIO_TURNO)
        """
        cursor.execute(query_turnos)
        prestamos_por_turno = rows_to_dicts(cursor, cursor.fetchall())

        query_pendientes = """
            SELECT u.USUARIO, COUNT(p.ID_PRESTAMO) as PENDIENTES
            FROM USUARIOS u
            LEFT JOIN PRESTAMOS p ON u.ID = p.ID_AUXILIAR AND p.ESTATUS = 'Activo' AND p.FECHA_HORA >= TRUNC(LOCALTIMESTAMP)
            WHERE u.TIPO = 1 GROUP BY u.USUARIO
        """
        cursor.execute(query_pendientes)
        pendientes_data = rows_to_dicts(cursor, cursor.fetchall())
        
        pendientes_map = {item['USUARIO']: item['PENDIENTES'] for item in pendientes_data}
        for turno in prestamos_por_turno:
            turno['PRESTAMOS_PENDIENTES'] = pendientes_map.get(turno['USUARIO'], 0)
        datos_dashboard['prestamos_por_turno'] = prestamos_por_turno

        cursor.execute("SELECT m.NOMBRE, SUM(dp.CANTIDAD_PRESTADA) as TOTAL FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL JOIN PRESTAMOS p ON dp.ID_PRESTAMO = p.ID_PRESTAMO WHERE p.FECHA_HORA >= TRUNC(LOCALTIMESTAMP) GROUP BY m.NOMBRE ORDER BY TOTAL DESC FETCH FIRST 5 ROWS ONLY"); datos_dashboard['top_materiales_hoy'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE CANTIDAD_DISPONIBLE <= 5 AND CANTIDAD_DISPONIBLE > 0 ORDER BY CANTIDAD_DISPONIBLE ASC"); datos_dashboard['materiales_bajo_stock'] = rows_to_dicts(cursor, cursor.fetchall())
        cursor.execute("SELECT u.USUARIO, ra.PRESTAMOS_PENDIENTES, ra.FECHA_HORA FROM REGISTRO_ACTIVIDAD ra JOIN USUARIOS u ON ra.ID_USUARIO = u.ID WHERE ra.TIPO_ACCION = 'CIERRE_SESION' AND ra.PRESTAMOS_PENDIENTES > 0 AND ra.FECHA_HORA >= TRUNC(LOCALTIMESTAMP) ORDER BY ra.FECHA_HORA DESC"); datos_dashboard['incidentes_cierre_sesion'] = rows_to_dicts(cursor, cursor.fetchall())
    except Exception as e: flash(f"Error al generar reportes: {e}", "danger"); traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return render_template('reportes.html', datos=datos_dashboard)

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
            SELECT ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD AS CANTIDAD_TOTAL, CANTIDAD_DISPONIBLE,
                   (CANTIDAD - CANTIDAD_DISPONIBLE) AS CANTIDAD_EN_USO,
                   CASE WHEN CANTIDAD_DISPONIBLE = 0 THEN 'Sin stock' WHEN CANTIDAD_DISPONIBLE < CANTIDAD THEN 'En uso' ELSE 'Disponible' END AS ESTATUS
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
        cursor.execute("INSERT INTO MATERIALES (ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, CANTIDAD_DISPONIBLE) VALUES (:id, :n, :t, :m, :c, :cd)", id=nuevo_id, n=nombre, t=tipo, m=marca_modelo, c=cantidad, cd=cantidad)
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
        cursor.execute("UPDATE MATERIALES SET NOMBRE = :n, TIPO = :t, MARCA_MODELO = :m, CANTIDAD = :c, CANTIDAD_DISPONIBLE = :cd WHERE ID_MATERIAL = :id", n=nombre, t=tipo, m=marca_modelo, c=cantidad, cd=nueva_cantidad_disponible, id=id_material)
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
            cursor.execute("SELECT m.NOMBRE, dp.CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO dp JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL WHERE dp.ID_PRESTAMO = :id_p", id_p=prestamo['ID_PRESTAMO'])
            materiales_prestados = rows_to_dicts(cursor, cursor.fetchall())
            prestamo['MATERIALES_LISTA'] = ', '.join([f"{m['NOMBRE']} (x{m['CANTIDAD_PRESTADA']})" for m in materiales_prestados])
            prestamos_con_materiales.append(prestamo)
        return render_template('prestamos.html', materiales_disponibles=materiales_disponibles, materias=materias, maestros=maestros, prestamos_activos=prestamos_con_materiales, **user_context)
    except Exception as e:
        flash(f"Error al cargar préstamos: {e}", "danger"); traceback.print_exc()
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

@app.route('/registrar_prestamo', methods=['POST'])
def registrar_prestamo():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn: flash("Error de conexión.", 'danger'); return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        no_control = request.form['no_control']
        materiales_seleccionados = json.loads(request.form['materiales_seleccionados'])
        if not materiales_seleccionados:
            flash('No se seleccionó ningún material.', 'warning'); return redirect(url_for('prestamos'))
        cursor.execute("SELECT ID_ALUMNO FROM ALUMNOS WHERE NUMEROCONTROL = :nc", nc=no_control)
        result = cursor.fetchone()
        if not result:
            flash(f"No se encontró ningún alumno con el número de control: {no_control}", "danger")
            return redirect(url_for('prestamos'))
        id_alumno = result[0]
        id_prestamo_var = cursor.var(cx_Oracle.NUMBER)
        cursor.execute("INSERT INTO PRESTAMOS (ID_ALUMNO, ID_MATERIA, ID_MAESTRO, ID_AUXILIAR, NUMERO_MESA, ESTATUS, FECHA_HORA) VALUES (:id_a, :id_m, :id_ma, :id_aux, :mesa, 'Activo', LOCALTIMESTAMP) RETURNING ID_PRESTAMO INTO :id_p_out", id_a=id_alumno, id_m=request.form['materia'], id_ma=request.form['maestro'], id_aux=session['user_id'], mesa=request.form.get('mesa'), id_p_out=id_prestamo_var)
        id_nuevo_prestamo = id_prestamo_var.getvalue()[0]
        for id_material, cantidad in materiales_seleccionados.items():
            cursor.execute("INSERT INTO DETALLE_PRESTAMO (ID_PRESTAMO, ID_MATERIAL, CANTIDAD_PRESTADA) VALUES (:p, :m, :c)", p=id_nuevo_prestamo, m=int(id_material), c=int(cantidad))
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE - :c WHERE ID_MATERIAL = :m", c=int(cantidad), m=int(id_material))
        conn.commit()
        flash('Préstamo registrado exitosamente.', 'success')
    except Exception as e:
        conn.rollback()
        if 'no data found' in str(e): flash(f"Error: No se encontró un alumno con el número de control proporcionado.", "danger")
        else: flash(f'Error al registrar el préstamo: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn: cursor.close(); conn.close()
    return redirect(url_for('prestamos'))

@app.route('/devolver_prestamo', methods=['POST'])
def devolver_prestamo():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_prestamo = request.form.get('id_prestamo')
    if not id_prestamo:
        flash("ID de préstamo no encontrado.", "danger")
        return redirect(url_for('prestamos'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión.", 'danger')
        return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_MATERIAL, CANTIDAD_PRESTADA FROM DETALLE_PRESTAMO WHERE ID_PRESTAMO = :id_p", id_p=id_prestamo)
        materiales_a_devolver = rows_to_dicts(cursor, cursor.fetchall())
        for material in materiales_a_devolver:
            cursor.execute("UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :c WHERE ID_MATERIAL = :m", c=material['CANTIDAD_PRESTADA'], m=material['ID_MATERIAL'])
        cursor.execute("UPDATE PRESTAMOS SET ESTATUS = 'Devuelto' WHERE ID_PRESTAMO = :id_p", id_p=id_prestamo)
        conn.commit()
        flash('Material devuelto y stock actualizado.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error al procesar la devolución: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn:
            cursor.close()
            conn.close()
    return redirect(url_for('prestamos'))

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