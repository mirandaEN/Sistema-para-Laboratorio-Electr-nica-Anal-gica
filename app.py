from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import cx_Oracle
import re
import traceback 
import json

app = Flask(__name__)
app.secret_key = "supersecretkey" 

# Configuración del cliente de Oracle (asegúrate de que la ruta es correcta)
cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# --- CONEXIÓN A LA BASE DE DATOS ---
db_user = 'JEFE_LAB'
db_password = 'jefe123' 
dsn = 'localhost:1521/XEPDB1'

def get_db_connection():
    """Crea y retorna una conexión a la base de datos Oracle."""
    try:
        return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)
    except cx_Oracle.DatabaseError as e:
        print(f"--- ERROR DE CONEXIÓN A ORACLE: {e} ---")
        traceback.print_exc()
        return None

def rows_to_dicts(cursor, rows):
    """Convierte una lista de filas (tuplas) en una lista de diccionarios."""
    column_names = [d[0].upper() for d in cursor.description]
    return [dict(zip(column_names, row)) for row in rows]

# --- FUNCIONES DE AUTENTICACIÓN Y REGISTRO ---

def validar_usuario(usuario, contrasena):
    """Valida login y devuelve (id, tipo) si el usuario y contraseña son correctos."""
    conn = get_db_connection()
    if not conn: return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ID_USUARIO, TIPO 
            FROM USUARIOS 
            WHERE USUARIO = :usr AND CONTRASENA = :pwd
        """, usr=usuario, pwd=contrasena)
        result = cursor.fetchone() 
        return (result[0], result[1]) if result else None
    except Exception as e:
        print(f"Error Oracle en validar_usuario: {e}")
        return None
    finally:
        if conn:
            cursor.close()
            conn.close()

def usuario_existe(usuario):
    """Verifica si un usuario existe."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM USUARIOS WHERE USUARIO = :usr", usr=usuario)
        return cursor.fetchone() is not None
    except Exception as e:
        print(f"Error Oracle en usuario_existe: {e}")
        return False
    finally:
        if conn:
            cursor.close()
            conn.close()

def registrar_alumno(nombre, numero_control, correo, especialidad, semestre):
    """Inserta un alumno en la tabla alumnos."""
    conn = get_db_connection()
    if not conn: return "error"
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM ALUMNOS 
            WHERE NUMEROCONTROL = :nc OR CORREO = :cr
        """, nc=numero_control, cr=correo)
        existe = cursor.fetchone()[0]
        
        if existe > 0:
            return "duplicado"

        cursor.execute("""
            INSERT INTO ALUMNOS (nombre, numerocontrol, correo, especialidad, semestre)
            VALUES (:nombre, :nc, :cr, :esp, :sem)
        """, nombre=nombre, nc=numero_control, cr=correo, esp=especialidad, sem=semestre)
        conn.commit()
        return "ok"
    except Exception as e:
        print(f"Error Oracle en registrar_alumno: {e}")
        conn.rollback()
        return "error"
    finally:
        if conn:
            cursor.close()
            conn.close()

# --- FUNCIONES DE GESTIÓN DE INVENTARIO ---

def obtener_materiales():
    """Obtiene todos los materiales de la tabla MATERIALES."""
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", 'danger')
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, CANTIDAD_DISPONIBLE, ESTATUS
            FROM MATERIALES ORDER BY ID_MATERIAL
        """)
        rows = cursor.fetchall()
        materiales = rows_to_dicts(cursor, rows)
        return materiales
    except Exception as e: 
        print(f"Error al obtener_materiales: {e}")
        flash(f"Error al cargar el inventario: {str(e).splitlines()[0]}", 'danger')
        return []
    finally:
        if conn:
            cursor.close()
            conn.close()

def insertar_material(nombre, tipo, marca_modelo, cantidad):
    """Inserta un nuevo material, inicializando la cantidad disponible."""
    conn = get_db_connection()
    if not conn: return None, "error: sin conexión"
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT NVL(MAX(ID_MATERIAL), 0) + 1 FROM MATERIALES")
        nuevo_id = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO MATERIALES (ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, CANTIDAD_DISPONIBLE)
            VALUES (:id, :nombre, :tipo, :modelo, :cant, :cant_disp)
        """, id=nuevo_id, nombre=nombre, tipo=tipo, modelo=marca_modelo, cant=cantidad, cant_disp=cantidad)
        conn.commit()
        return nuevo_id, "ok"
    except Exception as e:
        conn.rollback()
        error_msg = str(e).splitlines()[0] 
        print(f"Error Oracle al insertar_material: {error_msg}")
        return None, f"error: {error_msg}"
    finally:
        if conn:
            cursor.close()
            conn.close()

def actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad):
    """Actualiza un material y recalcula la cantidad disponible."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT CANTIDAD, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE ID_MATERIAL = :id", id=id_material)
        material_actual = cursor.fetchone()
        if not material_actual:
            return False
        
        diferencia = cantidad - material_actual[0]
        nueva_cantidad_disponible = material_actual[1] + diferencia
        
        cursor.execute("""
            UPDATE MATERIALES 
            SET NOMBRE = :nombre, TIPO = :tipo, MARCA_MODELO = :modelo, CANTIDAD = :cant, CANTIDAD_DISPONIBLE = :cant_disp
            WHERE ID_MATERIAL = :id
        """, nombre=nombre, tipo=tipo, modelo=marca_modelo, cant=cantidad, cant_disp=nueva_cantidad_disponible, id=id_material)
        conn.commit()
        return cursor.rowcount > 0 
    except Exception as e:
        conn.rollback()
        print(f"Error Oracle al actualizar_material: {e}")
        return False
    finally:
        if conn:
            cursor.close()
            conn.close()

def eliminar_material_db(id_material):
    """Elimina un material de la tabla MATERIALES por su ID."""
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM MATERIALES WHERE ID_MATERIAL = :id", id=id_material)
        conn.commit()
        return cursor.rowcount > 0 
    except Exception as e:
        conn.rollback()
        print(f"Error Oracle al eliminar_material_db: {e}")
        return False
    finally:
        if conn:
            cursor.close()
            conn.close()
        
# --- RUTAS DE LA APLICACIÓN ---

@app.route("/", methods=["GET", "POST"])
def login():
    """Login jefe/auxiliar"""
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()
        
        user_data = validar_usuario(usuario, contrasena)
        if user_data is None:
            if usuario_existe(usuario):
                flash("Verifica tu usuario y contraseña", "danger")
            else:
                flash("El usuario que ingresaste no existe", "danger")
        else:
            user_id, user_tipo = user_data
            session['user_id'] = user_id
            session['user_rol'] = 'admin' if user_tipo == 0 else 'auxiliar'
            session['user_nombre'] = usuario
            
            if user_tipo == 0:
                return redirect(url_for("interface_admin"))
            elif user_tipo == 1:
                return redirect(url_for("interface_aux"))

    return render_template("inicioAdmin.html")

@app.route("/interface_admin")
def interface_admin():
    return render_template("interfaceAdmin.html")

@app.route("/interface_aux")
def interface_aux():
    return render_template("interfaceAux.html")

@app.route("/registro_alumno", methods=["GET", "POST"])
def registro_alumno():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        numero_control = request.form.get("numero_control", "").strip()
        correo = request.form.get("correo", "").strip()
        especialidad = request.form.get("carrera", "").strip()
        semestre = request.form.get("semestre", "").strip()

        if not all([nombre, numero_control, correo, especialidad, semestre]):
            flash("Completa todos los campos.", "warning")
            return render_template("inicioAlumno.html")
        
        resultado = registrar_alumno(nombre, numero_control, correo, especialidad, int(semestre))

        if resultado == "duplicado":
            flash("El número de control o correo ya están registrados.", "error")
        elif resultado == "ok":
            flash("Te has registrado con éxito.", "success")
        else:
            flash("Error al registrar alumno. Intenta de nuevo.", "error")

    return render_template("inicioAlumno.html")

# --- RUTAS DE INVENTARIO ---

@app.route('/inventario')
def inventario():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    materiales = obtener_materiales()
    return render_template('inventario.html', 
                           materiales=materiales,
                           usuario_rol=session.get('user_rol'))

@app.route('/agregar_material', methods=['POST'])
def agregar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    
    if not nombre or not cantidad:
        flash('Nombre y Cantidad son obligatorios.', 'danger')
        return redirect(url_for('inventario'))
    try:
        cantidad_int = int(cantidad)
        if cantidad_int <= 0: raise ValueError
    except ValueError:
        flash('La cantidad debe ser un número entero positivo.', 'danger')
        return redirect(url_for('inventario'))
    nuevo_id, resultado = insertar_material(nombre, tipo, marca_modelo, cantidad_int)
    if resultado == "ok":
        flash(f'Material "{nombre}" agregado (ID: {nuevo_id}).', 'success')
    else:
        flash(f'Error al agregar material: {resultado}', 'danger')
    return redirect(url_for('inventario'))

@app.route('/modificar_material', methods=['POST'])
def modificar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_material_str = request.form.get('id_material')
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    if not all([id_material_str, nombre, cantidad]):
        flash('Faltan campos obligatorios para modificar.', 'danger')
        return redirect(url_for('inventario'))
    try:
        id_material = int(id_material_str)
        cantidad_int = int(cantidad)
        if cantidad_int < 0: raise ValueError
    except ValueError:
        flash('ID o Cantidad tienen formato incorrecto.', 'danger')
        return redirect(url_for('inventario'))
    if actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad_int):
        flash(f'Material ID {id_material} modificado.', 'warning')
    else:
        flash(f'Error: No se pudo actualizar el material ID {id_material}.', 'danger')
    return redirect(url_for('inventario'))

@app.route('/eliminar_material', methods=['POST'])
def eliminar_material():
    if 'user_id' not in session: return redirect(url_for('login'))
    id_material_str = request.form.get('id_material')
    if not id_material_str:
        flash('ID no proporcionado.', 'danger')
        return redirect(url_for('inventario'))
    try:
        id_material = int(id_material_str)
    except ValueError:
        flash('ID de material inválido.', 'danger')
        return redirect(url_for('inventario'))
    if eliminar_material_db(id_material):
        flash(f'Material ID {id_material} eliminado.', 'success')
    else:
        flash(f'Error al eliminar el material ID {id_material}.', 'danger')
    return redirect(url_for('inventario'))

# ==================================================================
# =============== SECCIÓN DE PRÉSTAMOS (CORREGIDA) =================
# ==================================================================

@app.route('/prestamos')
def prestamos():
    if 'user_id' not in session:
        flash('Por favor, inicia sesión para acceder.', 'warning')
        return redirect(url_for('login'))

    conn = get_db_connection()
    if not conn:
        flash("Error de conexión a la base de datos.", 'danger')
        return render_template('prestamos.html', materiales_disponibles=[], materias=[], maestros=[], prestamos_activos=[])
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT ID_MATERIAL, NOMBRE, CANTIDAD_DISPONIBLE FROM MATERIALES WHERE CANTIDAD_DISPONIBLE > 0 ORDER BY NOMBRE")
        materiales_disponibles = rows_to_dicts(cursor, cursor.fetchall())
        
        cursor.execute("SELECT ID_MATERIA, NOMBRE_MATERIA FROM MATERIAS ORDER BY NOMBRE_MATERIA")
        materias = rows_to_dicts(cursor, cursor.fetchall())

        cursor.execute("SELECT ID_MAESTRO, NOMBRE_COMPLETO FROM MAESTROS ORDER BY NOMBRE_COMPLETO")
        maestros = rows_to_dicts(cursor, cursor.fetchall())

        cursor.execute("""
            SELECT p.ID_PRESTAMO, a.NOMBRE, a.NUMEROCONTROL, p.FECHA_HORA
            FROM PRESTAMOS p
            JOIN ALUMNOS a ON p.ID_ALUMNO = a.ID_ALUMNO
            WHERE p.ESTATUS = 'Activo' 
              AND p.FECHA_HORA >= TRUNC(CURRENT_TIMESTAMP) 
              AND p.FECHA_HORA < TRUNC(CURRENT_TIMESTAMP) + 1
            ORDER BY p.FECHA_HORA DESC
        """)
        prestamos_activos_base = rows_to_dicts(cursor, cursor.fetchall())
        
        prestamos_con_materiales = []
        for prestamo in prestamos_activos_base:
            cursor.execute("""
                SELECT m.NOMBRE, dp.CANTIDAD_PRESTADA
                FROM DETALLE_PRESTAMO dp
                JOIN MATERIALES m ON dp.ID_MATERIAL = m.ID_MATERIAL
                WHERE dp.ID_PRESTAMO = :id_p
            """, id_p=prestamo['ID_PRESTAMO'])
            materiales_prestados = rows_to_dicts(cursor, cursor.fetchall())
            lista_materiales_str = ', '.join([f"{m['NOMBRE']} (x{m['CANTIDAD_PRESTADA']})" for m in materiales_prestados])
            prestamo['MATERIALES_LISTA'] = lista_materiales_str
            prestamos_con_materiales.append(prestamo)

        return render_template('prestamos.html', 
                               usuario_rol=session.get('user_rol'),
                               current_user={'nombre': session.get('user_nombre')},
                               materiales_disponibles=materiales_disponibles,
                               materias=materias,
                               maestros=maestros,
                               prestamos_activos=prestamos_con_materiales)
    except Exception as e:
        flash(f"Error al cargar la página de préstamos: {e}", "danger")
        traceback.print_exc()
        return render_template('prestamos.html', materiales_disponibles=[], materias=[], maestros=[], prestamos_activos=[])
    finally:
        if conn:
            cursor.close()
            conn.close()

@app.route('/api/alumno/<numerocontrol>')
def get_alumno(numerocontrol):
    if 'user_id' not in session:
        return jsonify({'error': 'No autorizado'}), 401
    
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Error de base de datos'}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT ID_ALUMNO, NOMBRE, SEMESTRE FROM ALUMNOS WHERE NUMEROCONTROL = :nc", nc=numerocontrol)
        rows = cursor.fetchall()
        if rows:
            alumno = rows_to_dicts(cursor, rows)[0]
            return jsonify(alumno)
        else:
            return jsonify({'error': 'Alumno no encontrado'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            cursor.close()
            conn.close()

@app.route('/registrar_prestamo', methods=['POST'])
def registrar_prestamo():
    if 'user_id' not in session: return redirect(url_for('login'))
    conn = get_db_connection()
    if not conn:
        flash("Error de conexión, no se pudo registrar el préstamo.", 'danger')
        return redirect(url_for('prestamos'))
    try:
        cursor = conn.cursor()
        
        no_control = request.form['no_control']
        id_materia = request.form['materia']
        id_maestro = request.form['maestro']
        numero_mesa = request.form.get('mesa') or None
        id_auxiliar = session['user_id']
        materiales_seleccionados = json.loads(request.form['materiales_seleccionados'])

        if not materiales_seleccionados:
            flash('No se seleccionó ningún material.', 'warning')
            return redirect(url_for('prestamos'))

        cursor.execute("SELECT ID_ALUMNO FROM ALUMNOS WHERE NUMEROCONTROL = :nc", nc=no_control)
        resultado_alumno = cursor.fetchone()
        if not resultado_alumno:
            flash('El número de control del alumno no es válido.', 'danger')
            return redirect(url_for('prestamos'))
        id_alumno = resultado_alumno[0]

        id_prestamo_var = cursor.var(cx_Oracle.NUMBER)
        
        # ✅ --- CORRECCIÓN FINAL: Usamos CURRENT_TIMESTAMP --- ✅
        # Esto asegura que la fecha y hora del préstamo sean las de la zona horaria local.
        cursor.execute("""
            INSERT INTO PRESTAMOS (ID_ALUMNO, ID_MATERIA, ID_MAESTRO, ID_AUXILIAR, NUMERO_MESA, ESTATUS, FECHA_HORA)
            VALUES (:id_a, :id_m, :id_ma, :id_aux, :mesa, 'Activo', CURRENT_TIMESTAMP)
            RETURNING ID_PRESTAMO INTO :id_p_out
        """, id_a=id_alumno, id_m=id_materia, id_ma=id_maestro, id_aux=id_auxiliar, mesa=numero_mesa, id_p_out=id_prestamo_var)
        id_nuevo_prestamo = id_prestamo_var.getvalue()[0]

        for id_material, cantidad in materiales_seleccionados.items():
            cursor.execute("""
                INSERT INTO DETALLE_PRESTAMO (ID_PRESTAMO, ID_MATERIAL, CANTIDAD_PRESTADA)
                VALUES (:id_p, :id_mat, :cant)
            """, id_p=id_nuevo_prestamo, id_mat=int(id_material), cant=int(cantidad))
            cursor.execute("""
                UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE - :cant
                WHERE ID_MATERIAL = :id_mat
            """, cant=int(cantidad), id_mat=int(id_material))
        
        conn.commit()
        flash('Préstamo registrado exitosamente.', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error al registrar el préstamo: {e}', 'danger')
        traceback.print_exc()
    finally:
        if conn:
            cursor.close()
            conn.close()
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
            cursor.execute("""
                UPDATE MATERIALES SET CANTIDAD_DISPONIBLE = CANTIDAD_DISPONIBLE + :cant
                WHERE ID_MATERIAL = :id_mat
            """, cant=material['CANTIDAD_PRESTADA'], id_mat=material['ID_MATERIAL'])
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

@app.route('/simulador_multimetro')
def simulador_multimetro():
    return render_template('simulador_multimetro.html')

if __name__ == "__main__":
    app.run(debug=True)





