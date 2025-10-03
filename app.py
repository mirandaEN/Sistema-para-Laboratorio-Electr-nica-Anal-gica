from flask import Flask, render_template, request, redirect, url_for, flash
import cx_Oracle
import re
import traceback 

app = Flask(__name__)
app.secret_key = "supersecretkey"



cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# datos de conexión a Oracle
db_user = 'JEFE_LAB'
db_password = 'jefe123'
dsn = 'localhost:1521/XEPDB1'
def get_db_connection():
    return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)

# conexión
def _conn():
    return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)



def validar_usuario(usuario, contrasena):
    """Valida login y devuelve tipo si usuario y contraseña son correctos"""
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT tipo 
                    FROM usuarios 
                    WHERE usuario = :usr AND contrasena = :pwd
                """, usr=usuario, pwd=contrasena)
                result = cursor.fetchone()
                return int(result[0]) if result else None
    except cx_Oracle.DatabaseError as e:
        print("Error Oracle en validar_usuario:", e)
        return None


def usuario_existe(usuario):
    """Verifica si un usuario existe (sin validar contraseña)"""
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM usuarios WHERE usuario = :usr", usr=usuario)
                return cursor.fetchone() is not None
    except cx_Oracle.DatabaseError as e:
        print("Error Oracle en usuario_existe:", e)
        return False


def registrar_alumno(nombre, numero_control, correo, especialidad, semestre):
    """Inserta un alumno en la tabla alumnos"""
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                # verificar si ya existe (por número de control o correo)
                cursor.execute("""
                    SELECT COUNT(*) FROM alumnos 
                    WHERE numerocontrol = :nc OR correo = :cr
                """, nc=numero_control, cr=correo)
                existe = cursor.fetchone()[0]
                if existe > 0:
                    return "duplicado"

                # insertar alumno
                cursor.execute("""
                    INSERT INTO alumnos (nombre, numerocontrol, correo, especialidad, semestre)
                    VALUES (:nombre, :nc, :cr, :esp, :sem)
                """, nombre=nombre, nc=numero_control, cr=correo, esp=especialidad, sem=semestre)
                connection.commit()
                return "ok"
    except cx_Oracle.DatabaseError as e:
        print("Error Oracle en registrar_alumno:", e)
        return "error"
        


def obtener_materiales():
    """Obtiene todos los materiales de la tabla MATERIALES y los formatea."""
    materiales = []
    conn = None # Inicializar la conexión
    try:
        conn = _conn()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD, ESTATUS,
                    CANTIDAD AS CANTIDAD_DISPONIBLE 
                FROM MATERIALES ORDER BY ID_MATERIAL
            """)
            
            cols = [d[0].upper() for d in cursor.description]
            
            for row in cursor.fetchall():
                materiales.append(dict(zip(cols, row)))
                    
    except Exception as e: 
        print("--- CRITICAL INVENTORY ERROR ---")
        print(f"Error al obtener_materiales: {e}")
        traceback.print_exc()
        print("----------------------------------")
        
        error_msg = str(e).splitlines()[0]
        flash(f"Error al cargar el inventario. Revisa el nombre de la columna ESTATUS o tu conexión. Detalle: {error_msg}", 'danger')
        return []
    finally:
        if conn:
            conn.close()
    
    return materiales


def insertar_material(nombre, tipo, marca_modelo, cantidad):
    """
    Inserta un nuevo material. ESTATUS se excluye de la sentencia INSERT por ser virtual.
    """
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT NVL(MAX(ID_MATERIAL), 0) + 1 FROM MATERIALES")
                nuevo_id = cursor.fetchone()[0]
                
                cursor.execute("""
                    INSERT INTO MATERIALES (ID_MATERIAL, NOMBRE, TIPO, MARCA_MODELO, CANTIDAD)
                    VALUES (:id, :nombre, :tipo, :modelo, :cant)
                """, id=nuevo_id, nombre=nombre, tipo=tipo, modelo=marca_modelo, cant=cantidad)
                connection.commit()
                return nuevo_id, "ok"
    except cx_Oracle.DatabaseError as e:
        error_msg = str(e).splitlines()[0] 
        print("Error Oracle al insertar_material:", error_msg)
        return None, f"error: {error_msg}"


def actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad):
    """
    Actualiza un material existente. ESTATUS se excluye de la sentencia UPDATE por ser virtual.
    """
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE MATERIALES 
                    SET NOMBRE = :nombre, TIPO = :tipo, MARCA_MODELO = :modelo, CANTIDAD = :cant
                    WHERE ID_MATERIAL = :id
                """, nombre=nombre, tipo=tipo, modelo=marca_modelo, cant=cantidad, id=id_material)
                connection.commit()
                return cursor.rowcount > 0 
    except cx_Oracle.DatabaseError as e:
        print("Error Oracle al actualizar_material:", e)
        return False


def eliminar_material_db(id_material):
    """Elimina un material de la tabla MATERIALES por su ID."""
    try:
        with _conn() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM MATERIALES WHERE ID_MATERIAL = :id", id=id_material)
                connection.commit()
                return cursor.rowcount > 0 
    except cx_Oracle.DatabaseError as e:
        print("Error Oracle al eliminar_material_db:", e)
        return False
        

@app.route("/", methods=["GET", "POST"])
def login():
    """Login jefe/auxiliar"""
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()

        if usuario and not re.match(r"^[A-Za-zÁÉÍÓÚáéíóúÑñ ]+$", usuario):
            flash("El usuario solo puede contener letras")
            return render_template("inicioAdmin.html")

        if not usuario and not contrasena:
            flash("Ingresa tu usuario y contraseña")
        elif usuario and not contrasena:
            flash("Ingresa tu contraseña")
        elif contrasena and not usuario:
            flash("Ingresa tu usuario")
        else:
            tipo = validar_usuario(usuario, contrasena)
            if tipo is None:
                if usuario_existe(usuario):
                    flash("Verifica tu usuario y contraseña")
                else:
                    flash("El usuario y contraseña que ingresaste no existen")
            else:
                if tipo == 0:  # jefe
                    return redirect(url_for("interface_admin"))
                elif tipo == 1:  # auxiliar
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
    """Registro de alumnos"""
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        numero_control = request.form.get("numero_control", "").strip()
        correo = request.form.get("correo", "").strip()
        especialidad = request.form.get("carrera", "").strip()
        semestre = request.form.get("semestre", "").strip()

        if not nombre or not numero_control or not correo or not especialidad or not semestre:
            flash("Completa los campos faltantes")
            return render_template("inicioAlumno.html")

        if not re.match(r"^[A-Za-zÁÉÍÓÚáéíóúÑñ ]+$", nombre):
            flash("Verifica el formato de los datos ingresados")
            return render_template("inicioAlumno.html")

        if not re.match(r"^[0-9]+$", numero_control):
            flash("Verifica el formato de los datos ingresados")
            return render_template("inicioAlumno.html")

        if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", correo):
            flash("Verifica el formato de los datos ingresados")
            return render_template("inicioAlumno.html")

        resultado = registrar_alumno(nombre, numero_control, correo, especialidad, int(semestre))

        if resultado == "duplicado":
            flash("Ya estás registrado", "error")
        elif resultado == "ok":
            flash("Te haz registrado con éxito", "success")
        else:
            flash("Error al registrar alumno. Intenta de nuevo.", "error")

    return render_template("inicioAlumno.html")



@app.route('/inventario')
def inventario():
    """Ruta principal: Muestra la tabla de inventario."""
    materiales = obtener_materiales()
    return render_template('inventario.html', materiales=materiales)

@app.route('/agregar_material', methods=['POST'])
def agregar_material():
    """Ruta para agregar un nuevo material."""
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    
    if not nombre or not cantidad:
        flash('Advertencia: Llenar los campos obligatorios: Nombre y Cantidad (*).', 'danger')
        return redirect(url_for('inventario'))
        
    try:
        cantidad_int = int(cantidad)
        if cantidad_int <= 0:
            flash('Advertencia: La cantidad debe ser un número entero positivo.', 'danger')
            return redirect(url_for('inventario'))
    except ValueError:
        flash('Error: La cantidad debe ser un número entero válido.', 'danger')
        return redirect(url_for('inventario'))

    nuevo_id, resultado = insertar_material(nombre, tipo, marca_modelo, cantidad_int)
    
    if resultado == "ok":
        flash(f'Material "{nombre}" agregado exitosamente (ID: {nuevo_id}).', 'success')
    else:
        flash(f'Error al agregar material en la base de datos: {resultado}', 'danger')

    return redirect(url_for('inventario'))

@app.route('/modificar_material', methods=['POST'])
def modificar_material():
    """Ruta para modificar un material existente."""
    id_material_str = request.form.get('id_material')
    nombre = request.form.get('nombre', '').strip()
    tipo = request.form.get('tipo', '').strip()
    marca_modelo = request.form.get('marca_modelo', '').strip()
    cantidad = request.form.get('cantidad')
    if not id_material_str or not nombre or not cantidad:
        flash('Advertencia: Llenar los campos obligatorios para modificar.', 'danger')
        return redirect(url_for('inventario'))
    
    try:
        id_material = int(id_material_str)
        cantidad_int = int(cantidad)
        if cantidad_int <= 0:
            flash('Advertencia: La cantidad debe ser un número entero positivo.', 'danger')
            return redirect(url_for('inventario'))
    except ValueError:
        flash('Error en el formato de ID o Cantidad.', 'danger')
        return redirect(url_for('inventario'))

    if actualizar_material(id_material, nombre, tipo, marca_modelo, cantidad_int):
        flash(f'Material "{nombre}" (ID: {id_material}) modificado exitosamente.', 'warning')
    else:
        flash(f'Error: No se encontró el material con ID {id_material} o no se pudo actualizar.', 'danger')

    return redirect(url_for('inventario'))


@app.route('/eliminar_material', methods=['POST'])
def eliminar_material():
    """Ruta para eliminar un material."""
    id_material_str = request.form.get('id_material')
    
    if not id_material_str:
        flash('Error: ID de material no proporcionado para eliminar.', 'danger')
        return redirect(url_for('inventario'))
        
    try:
        id_material = int(id_material_str)
    except ValueError:
        flash('Error: ID de material inválido.', 'danger')
        return redirect(url_for('inventario'))

    if eliminar_material_db(id_material):
        flash(f'Material (ID: {id_material}) eliminado correctamente.', 'success')
    else:
        flash(f'Error: No se pudo encontrar el material con ID {id_material} para eliminar.', 'danger')

    return redirect(url_for('inventario'))


# Ejecutar la aplicación
if __name__ == "__main__":
    app.run(debug=True)