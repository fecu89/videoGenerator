# Video Generator

[English](README.md) · [한국어](README.ko.md) · [日本語](README.ja.md) · [简体中文](README.zh-CN.md) · **Español**

Le das un tema y un agente de IA investiga, escribe el guion, le pone voz y construye las imágenes en 3D hasta terminar un vídeo explicativo. Esta carpeta es el espacio de trabajo para eso.

Lo único que hace la persona es **elegir, leer, anotar lo que hay que corregir y aprobar**. No hace falta escribir código ni memorizar comandos. En cada paso importante se abre una página web, y ahí pulsas un botón o escribes tus comentarios.

> **Nota sobre el idioma.** La herramienta está pensada primero para coreano: la narración principal es en coreano, y las pantallas web y los archivos de instrucciones del agente están escritos en coreano. Los nombres de los botones aparecen aquí tal como se ven en pantalla, con su traducción al lado.

![Escenas de un vídeo terminado](readme/sample.png)

*Escenas de «Por qué Saturno tiene anillos» (2 min 38 s), hecho con esta carpeta.*

<sub>Modelos 3D de la imagen, usados con modificaciones: ["Saturn"](https://sketchfab.com/3d-models/saturn-c09a1970148c43ad99db134a9d6d00b5) by Nestaeric, ["Asteroids Pack (rocky version)"](https://sketchfab.com/3d-models/asteroids-pack-rocky-version-adde1ecf129e4509be8af61b84bafa85) by SebastianSosnowski, ["Wandering Asteroids Of Andromeda"](https://sketchfab.com/3d-models/wandering-asteroids-of-andromeda-6a8e84e0fdea43628b8b3ab85b130281) by ARCTIC WOLVES™, ["Asteroid low poly"](https://sketchfab.com/3d-models/asteroid-low-poly-9a43ef48a70647188576ccb5987b7e64) by pasquill. Todos con licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).</sub>

## Qué produce

- Un vídeo explicativo en coreano de 1 a 3 minutos (horizontal, vertical o cuadrado)
- Narración en coreano y música de fondo
- Voz y subtítulos en inglés, japonés, chino y español (solo los idiomas que elijas)

Las imágenes no son vídeo generativo. Son escenas 3D calculadas y dibujadas en Blender, de modo que lo que tiene que ser exacto —la posición de un astro, la dirección de una fuerza— no cambia de una escena a otra.

## Requisitos

| Qué necesitas | Para qué |
|---|---|
| Mac con Apple silicon (M1 o posterior) | Los modelos de voz solo funcionan en este entorno |
| Un agente de programación con IA (Claude Code, Codex, etc.) | Se encarga de la investigación, el guion y el diseño visual |
| Python 3.13 | La herramienta en sí |
| FFmpeg | Une el vídeo y el audio |
| Blender 5.2 | Dibuja las escenas 3D. Instálalo en `/Applications/Blender.app` |
| espeak-ng | Solo hace falta para la voz en español |

## Instalación

En una terminal, entra en esta carpeta y ejecuta lo siguiente una sola vez. Si no lo tienes claro, puedes decirle al agente «instálalo siguiendo el README».

```bash
python3 -m pip install -r requirements.txt
brew install ffmpeg espeak-ng
```

Descarga Blender desde [blender.org](https://www.blender.org/download/) y colócalo en la carpeta Aplicaciones.

Los modelos de voz se descargan automáticamente la primera vez que generas una voz. Es el único momento en que hace falta conexión a internet, y tarda unos minutos. Después todo funciona en este ordenador, sin internet ni clave de API.

## Cómo empezar

Abre esta carpeta con tu agente y dile algo así:

> Haz un vídeo siguiendo el flujo de generación de vídeo. El tema es «Por qué Saturno tiene anillos».

Si tienes un borrador del guion, pégalo también. También puedes darle un PDF y pedirle que haga el vídeo a partir de su contenido. Si hay un modelo 3D que quieras usar, ponlo en la carpeta `assets/` y díselo al agente.

El agente sigue el orden descrito en [AGENTS.md](AGENTS.md). La persona interviene solo en las seis etapas siguientes.

## El flujo completo

| Etapa | Qué hace el agente | Qué haces tú |
|---|---|---|
| 1. Ajustes | Abre la página de ajustes | Elige ritmo, voz, música y salida, y pulsa **저장 후 닫기** (Guardar y cerrar) |
| 2. Guion | Investiga, redacta el borrador del guion y lo muestra en la web | Léelo y deja comentarios, o pulsa **대본 승인** (Aprobar guion) |
| 3. Voz | Genera la voz a partir del guion aprobado | Esperar |
| 4. Vista previa | Diseña las imágenes, dibuja fotogramas representativos y los muestra en la web | Míralos y deja comentarios, o pulsa **프리뷰 승인** (Aprobar vista previa) |
| 5. Borrador | Genera el vídeo completo en baja resolución | Reprodúcelo y responde `초본승인` («borrador aprobado») en el chat |
| 6. Versión final | Lo vuelve a generar en la resolución original | Esperar |

Hay tres aprobaciones: guion, vista previa y borrador. La etapa siguiente no empieza hasta que se aprueba la anterior. Así se evita gastar trabajo de larga duración en un guion o unas imágenes equivocados.

### Etapa 1 — Elegir los ajustes

![Página de ajustes](readme/settings.png)

Solo tienes que mirar los cuatro grupos de la lista de la izquierda.

- **영상 템포** (Ritmo del vídeo): explicación pausada / vídeo normal / ritmo de vídeo corto. Determina a la vez la velocidad del habla y cada cuánto cambia la imagen.
- **목소리** (Voz): elige el tono general. Despliega **목소리 미리 듣기** (Escuchar la voz) para oírla antes de guardar.
- **배경음악** (Música de fondo): elige entre la música de la carpeta `bgmusic/` y ajusta el volumen. Déjalo vacío para no poner música.
- **출력** (Salida): elige el formato del vídeo, los idiomas adicionales y si los subtítulos van incrustados en el vídeo o aparte.

Cuando termines, pulsa **저장 후 닫기** (Guardar y cerrar) abajo a la derecha. Al cerrarse la ventana, el agente pasa a la etapa siguiente. Los ajustes de la última vez se conservan, así que si no hay nada que cambiar puedes cerrar directamente.

**고급 옵션** (Opciones avanzadas) está plegado. Normalmente no hace falta abrirlo. Cada opción se explica en [settings.md](settings.md).

### Etapa 2 — Revisar el guion

![Página de revisión del guion](readme/story.png)

- Elige una escena en la **lista de la izquierda** y en el centro aparecen su guion y lo que se mostrará en pantalla.
- Escribe lo que hay que corregir en **이 장면의 수정 사항** (Cambios para esta escena). Basta con lenguaje corriente: «esta frase repite la escena anterior», «explícalo de forma más sencilla».
- **영상 아이디어** (Ideas para el vídeo) es opcional. Si quieres alguna imagen o un enfoque concreto, escríbelo; si no, déjalo vacío.
- Para comentarios sobre el vídeo entero, despliega **영상 전체에 대한 수정 의견** (Comentarios sobre todo el vídeo), al final de la página.

Cuando termines, pulsa un botón arriba a la derecha.

- **수정 의견 저장** (Guardar comentarios): cuando haya algo que corregir. Después de guardar, dile al agente «he dejado comentarios». La web no avisa al agente por sí sola.
- **대본 승인** (Aprobar guion): cuando esté bien tal cual. Al aprobar se cierra la página y empieza la generación de la voz.

Guardar sin aprobar no hace avanzar el proceso. Cuando el agente corrija el guion, recarga la misma página, vuelve a leerlo y aprueba.

### Etapa 3 — Generar la voz

El agente se encarga solo. Tarda unos minutos para unas veinte escenas.

A veces el modelo de voz lee una frase concreta demasiado despacio y no supera la comprobación. En ese caso el agente propone quitar una coma o retocar la frase. Como eso cambia el guion, vuelve a pedir tu aprobación.

### Etapa 4 — Revisar la vista previa

![Página de revisión de la vista previa](readme/preview.png)

Antes de dibujar el vídeo entero, primero ves unos cuantos fotogramas representativos de cada escena. Corregir aquí es lo más rápido.

- Pulsa las **imágenes pequeñas bajo la imagen grande** para recorrer esa escena en orden cronológico. Usa **이미지 크게 보기** (Ampliar imagen) para verla más grande.
- Con el botón de reproducción bajo **나레이션 대본** (Guion de narración) puedes escuchar la voz de esa escena.
- **영상대본** (Guion visual) describe con palabras lo que ocurre en pantalla en ese momento.
- Escribe tus comentarios sobre la imagen en **이 장면의 수정 사항** (Cambios para esta escena). Describe lo que ves: «la flecha es demasiado larga», «la luna aparece en escenas donde no hace falta».

Arriba a la derecha hay tres botones.

- **수정 의견 저장** (Guardar comentarios): solo guarda los comentarios.
- **수정 반영 후 프리뷰 다시 만들기** (Aplicar cambios y rehacer la vista previa): guarda los comentarios y pide una vista previa nueva. Al pulsarlo se cierra la página. Si el agente no continúa enseguida, dile «he enviado comentarios sobre la vista previa».
- **프리뷰 승인** (Aprobar vista previa): cuando esté bien tal cual. Al aprobar se cierra la página. No se puede pulsar mientras haya comentarios escritos.

Cuando el agente haga los cambios, la página de revisión se abre de nuevo con la vista previa nueva. Repite hasta que te convenza.

Las imágenes de la vista previa se dibujan pequeñas (384 píxeles en el lado largo). Sirven para comprobar rápido, así que los detalles pueden verse borrosos.

### Etapa 5 — Comprobar el borrador

Cuando apruebas la vista previa, el agente genera el vídeo completo en baja resolución y te indica dónde está `final-draft.mp4`. Incluye voz y música. Reprodúcelo tú y comprueba si hay movimientos poco naturales o pronunciaciones raras. El agente no puede reproducir el vídeo ni escuchar el audio.

- Si hay algo que corregir, dilo en el chat. Si solo cambian las imágenes, la voz no se vuelve a generar.
- Si está bien, responde `초본승인` («borrador aprobado») en el chat.

### Etapa 6 — Versión final

Se vuelve a dibujar en la resolución original. El agente te da la dirección de una página web que muestra el progreso, y al terminar el vídeo aparece en esa página.

Lleva bastante tiempo. En el vídeo de Saturno (2 min 38 s, 1920×1080), el borrador tardó unos 17 minutos y la versión final unas 2 horas y 15 minutos. Deja el ordenador encendido y dedícate a otra cosa.

## Dónde están los resultados

Cada vídeo tiene su propia carpeta `runs/<fecha>-<tema>/`.

| Archivo | Contenido |
|---|---|
| `final.mp4` | Vídeo terminado (voz en coreano, música de fondo) |
| `final-en.m4a`, etc. | Pistas de voz por idioma. Según los ajustes, pueden salir como vídeos por idioma, por ejemplo `final-en.mp4` |
| `subtitles/` | Archivos de subtítulos por idioma (`.srt`, `.ass`) |
| `video-only.mp4` | Vídeo sin sonido |
| `final-draft.mp4` | El borrador que comprobaste en la etapa 5 |
| `story-review.md` | Guion y fuentes |
| `research.md` | Notas de la investigación, y lo que las imágenes exageran u omiten |

La carpeta `runs/` no se sube a git. Guarda en otro sitio los vídeos que necesites.

## Conviene saber

- **Cuanto más concretos sean los comentarios, mejor.** «La flecha de la escena 9 no coincide con el centro de la luna» se corrige a la primera; «se ve raro», no. Indicar el número de escena ayuda todavía más.
- **«Adelante» no es una aprobación.** Solo cuenta como aprobación el botón de aprobar de la web o una aprobación clara en el chat («대본 승인», «프리뷰 승인», «초본승인»).
- **Si cambias el guion, la voz se vuelve a generar.** Si solo cambias las imágenes, la voz se mantiene. Por eso conviene pulir bien el guion en la etapa 2.
- **Un tema nuevo tarda más.** El agente tiene que escribir desde cero el código que dibuja las escenas de ese tema. Si se parece a un tema que ya hiciste, va mucho más rápido.
- **Los modelos 3D y la música externos tienen condiciones.** Anota el origen y la licencia de cada modelo que pongas en `assets/` en `assets/CREDITS.md`. La mayoría exige mencionar al autor al publicar el vídeo, y algunos son solo para uso no comercial o no permiten modificaciones.
- **Las traducciones las escribe el agente.** No hay revisión por parte de hablantes nativos. Algunas frases pueden ser más cortas que en coreano para ajustarse a la duración de cada escena.

## Estructura de carpetas

| Carpeta / archivo | Contenido | Git |
|---|---|---|
| `video_harness/` | La herramienta en sí (voz, imagen, comprobaciones, páginas web) | Incluido |
| `settings.json` | Los ajustes que elegiste la última vez | Incluido |
| `AGENTS.md` | El orden que sigue el agente | Incluido |
| `readme/` | Las imágenes de este documento | Incluido |
| `assets/` | Modelos 3D y tus notas sobre su origen | Excluido |
| `bgmusic/` | Música de fondo. Solo se incluye `README.md` | Excluido |
| `runs/` | Carpetas de trabajo y resultados de cada vídeo | Excluido |

## Más detalles (para desarrolladores)

Estos son los comandos que el agente usa internamente. Rara vez tendrás que ejecutarlos tú.

```bash
python -m video_harness settings-ui                 # página de ajustes
python -m video_harness story-ui runs/<run>         # página de revisión del guion
python -m video_harness voice runs/<run>/script.json
python -m video_harness preview runs/<run>          # comprobación del plan → render de fotogramas → página de vista previa
python -m video_harness preview-ui runs/<run>       # solo volver a abrir la vista previa
python -m video_harness produce runs/<run> --quality draft
python -m video_harness produce runs/<run> --quality final
python -m video_harness validate runs/<run>
```

Cuando el video final pasa las comprobaciones, el mismo comando crea además un short vertical por idioma (`shorts/shorts-<lang>.mp4`, solo con las escenas que el guion marca para el short, máximo 3 minutos) y `upload.md`: títulos y descripciones por idioma listos para copiar, con los créditos de los modelos 3D, la música y la voz. La página del video terminado los muestra con botones de copiar.

Los documentos siguientes están escritos en coreano.

- Flujo de trabajo completo y reglas de aprobación: [video_harness/agent/WORKFLOW.md](video_harness/agent/WORKFLOW.md)
- Criterios básicos de dirección para guion e imagen: [video_harness/agent/DIRECTION.md](video_harness/agent/DIRECTION.md)
- Arquitectura de la herramienta: [video_harness/docs/architecture.md](video_harness/docs/architecture.md)
- Cómo añadir una escena de Blender: [video_harness/docs/blender-rendering.md](video_harness/docs/blender-rendering.md)
- Comprobaciones de la cadena de preguntas y de la continuidad visual: [video_harness/docs/creative-gates.md](video_harness/docs/creative-gates.md)
- Principios de transición entre escenas: [video_harness/docs/continuous-transitions.md](video_harness/docs/continuous-transitions.md)
- Interpretación de la voz y pausas: [video_harness/docs/voice-acting.md](video_harness/docs/voice-acting.md)

Las pruebas se ejecutan sin clave de API ni descarga de modelos.

```bash
python -m pytest -q -p no:cacheprovider
```

La instalación adicional siguiente solo hace falta si usas el renderizador de Three.js o ejecutas las pruebas de navegador de las páginas web. Si solo trabajas con Blender, no es necesaria.

```bash
cd video_harness/science_renderer
npm ci
npx playwright install chromium --only-shell
```

## Licencia

[MIT](LICENSE). Se aplica al código de este repositorio. Los modelos 3D, la música y los modelos de voz que añadas o descargues conservan sus propias licencias.
