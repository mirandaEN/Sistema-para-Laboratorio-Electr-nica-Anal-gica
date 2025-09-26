from flask import Flask, render_template, request, redirect, url_for, flash
import cx_Oracle
import re

app = Flask(__name__)
app.secret_key = "supersecretkey"

# inicializar Oracle Client
cx_Oracle.init_oracle_client(lib_dir="/Users/mirandaestrada/instantclient_21_9")

# datos de conexión a Oracle
db_user = 'JEFE_LAB'
db_password = 'jefe123'
dsn = 'localhost:1521/XEPDB1'

# función para obtener conexión
def _conn():
    return cx_Oracle.connect(user=db_user, password=db_password, dsn=dsn)

#funciones de base de datos
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

#rutas de la aplicación
@app.route("/", methods=["GET", "POST"])
def login():
    """Login jefe/auxiliar"""
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        contrasena = request.form.get("contrasena", "").strip()

        # Validación: usuario solo letras
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


# Ejecutar la aplicación
if __name__ == "__main__":
    app.run(debug=True)
