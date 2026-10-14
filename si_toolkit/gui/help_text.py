# -*- coding: utf-8 -*-
"""
Testo della scheda "Aiuto" (HTML semplice per wx.html), in italiano e in
inglese. page(lang) ritorna la pagina nella lingua scelta.
"""

_IT = """
<h3>PCB Signal Integrity Toolkit - guida rapida</h3>
<p>Ogni scheda analizza un aspetto della board aperta in Pcbnew. Cliccando
una riga dei risultati si selezionano in Pcbnew le tracce corrispondenti.
I valori dei campi vengono ricordati fra un'apertura e l'altra; le
impostazioni comuni stanno nella scheda <b>Opzioni</b>.</p>

<h4>Return Path</h4>
{img:return_path}
<p>Controlla che sotto ogni traccia ci sia un piano di riferimento continuo
(net di riferimento, di solito GND). Segnala le tracce che attraversano
interruzioni del piano piu' larghe del <i>Gap minimo</i>. I marker sulla board:
<b>User.1</b> = nessuna via di stitching vicina (grave), <b>User.2</b> = via
vicina. <i>Pulisci overlay</i> li toglie.</p>

<h4>Corrente DC</h4>
{img:dc_current}
<p>Scegli la net, il pad di <b>ingresso</b> e una o piu' <b>uscite</b> con la
loro corrente (elenco vuoto = una sola uscita). Il calcolo risolve la rete
resistiva di tracce e via: corrente, caduta di tensione, densita' e
percentuale del limite IPC-2221 per ogni elemento (semaforo: verde &lt; 80%,
giallo 80-100%, rosso oltre). <i>Mappa a colori</i> mostra densita', % del
limite, tensione (IR drop, sfumata lungo le tracce) e corrente. Rame,
placcatura, DT ammesso e trattamento delle zone: scheda Opzioni.</p>

<h4>Impedenza</h4>
{img:impedance}
<p>Z0 di ogni gruppo di tracce (net/layer/larghezza) col risolutore di campo
2D, dallo stackup della scheda. Rileva da solo la massa laterale
(coplanare) e la copertura del piano sotto; se il <i>Piano sotto</i> e' sotto
circa il 90% il valore non e' affidabile. Le colonne <i>per target</i> danno
la larghezza o il gap che portano al valore voluto.</p>

<h4>Coppie diff.</h4>
{img:diff_pair}
<p>Riconosce le coppie dai nomi (_P/_N, DP/DM, +/-) oppure da due net
selezionate. Calcola Zdiff e Z di modo comune col risolutore di campo (modi
dispari e pari), con solder mask e massa laterale esterna, la differenza di
lunghezza P/N e la larghezza per il target.</p>

<h4>Crosstalk</h4>
{img:crosstalk}
<p>Trova tratti di net diverse paralleli e vicini sullo stesso layer e stima
il disturbo (NEXT, regola di Johnson) in base a spaziatura, lunghezza e
tempo di salita. E' una stima di ordine di grandezza per trovare i tratti
da guardare meglio.</p>

<h4>openEMS</h4>
{img:openems}
<p>Simulazione elettromagnetica 3D (FDTD) della linea selezionata con
openEMS, in una finestra separata. Risultati: S11, S21, impedenza
(results.png), TDR/TDT con il <i>tempo di salita</i> scelto e, se attivo
<i>Salva campi</i>, le GIF del campo (vista dall'alto, sezione, energia) alla
<i>tensione</i> scelta. <i>Rielabora</i> rifa' GIF e TDR senza risimulare.
Regola per la banda: f max &gt;= 1,2 / tempo di salita.
Python, cartella openEMS, cartella risultati e mesh: scheda Opzioni.</p>

<h4>Installare openEMS</h4>
<p>Il Plugin Manager installa solo il plugin: openEMS va installato a parte
(serve solo per la scheda openEMS).</p>
<ol>
<li>Scarica openEMS per Windows dalle release ufficiali di openEMS ed estrai
l'archivio in una cartella (es. <tt>D:\\Programmi\\openEMS</tt>).</li>
<li>Installa un Python a 64 bit (versione supportata dai moduli di quella
release di openEMS).</li>
<li>In <b>Opzioni</b> indica il Python e la cartella di openEMS, poi premi
<b>Verifica openEMS</b>: controlla tutto e dice cosa manca.</li>
<li>Se mancano numpy, h5py o matplotlib, oppure i moduli CSXCAD/openEMS
(installati dai file .whl della cartella di openEMS), il pulsante
<b>Installa pacchetti mancanti</b> li installa dopo conferma. Poi premi di
nuovo Verifica.</li>
</ol>

<h4>Opzioni</h4>
<p>Lingua, stackup (Er e dielettrico: <i>auto</i> = dalla scheda), net di
massa, solder mask, parametri della corrente DC e percorsi di openEMS.
Le cartelle dei risultati e' meglio tenerle fuori da OneDrive.</p>

<h4>Limiti da ricordare</h4>
<ul>
<li>Le analisi sono quasi-statiche (tranne openEMS): utili per confrontare e
trovare i problemi, non sostituiscono le misure.</li>
<li>Con <i>Zone = resistenza nulla</i> la corrente DC e' ottimistica; senza,
pessimistica.</li>
</ul>
"""

_EN = """
<h3>PCB Signal Integrity Toolkit - quick guide</h3>
<p>Each tab analyzes one aspect of the board open in Pcbnew. Clicking a
result row selects the corresponding tracks in Pcbnew. Field values are
remembered between sessions; shared settings are in the <b>Options</b> tab.</p>

<h4>Return Path</h4>
{img:return_path}
<p>Checks that every track has a continuous reference plane underneath
(reference net, usually GND). Reports tracks crossing plane gaps wider than
the <i>Minimum gap</i>. Board markers: <b>User.1</b> = no stitching via nearby
(severe), <b>User.2</b> = via nearby. <i>Clear overlay</i> removes them.</p>

<h4>DC Current</h4>
{img:dc_current}
<p>Choose the net, the <b>input</b> pad and one or more <b>outputs</b> with
their current (empty list = single output). The calculation solves the
resistive network of tracks and vias: current, voltage drop, density and
percentage of the IPC-2221 limit for each element (traffic light: green
&lt; 80%, yellow 80-100%, red above). <i>Color map</i> shows density, % of
limit, voltage (IR drop, shaded along the tracks) and current. Copper,
plating, allowed DT and zone handling: Options tab.</p>

<h4>Impedance</h4>
{img:impedance}
<p>Z0 of each track group (net/layer/width) with the 2D field solver, from
the board stackup. It detects side ground (coplanar) and plane coverage
below by itself; if <i>Plane below</i> is under about 90% the value is not
reliable. The <i>for target</i> columns give the width or gap that reach the
desired value.</p>

<h4>Diff. pairs</h4>
{img:diff_pair}
<p>Recognizes pairs from net names (_P/_N, DP/DM, +/-) or from two selected
nets. Computes Zdiff and common-mode Z with the field solver (odd and even
modes), including solder mask and outer side ground, the P/N length
difference and the width for the target.</p>

<h4>Crosstalk</h4>
{img:crosstalk}
<p>Finds parallel, close runs of different nets on the same layer and
estimates the noise (NEXT, Johnson's rule) from spacing, length and rise
time. It is an order-of-magnitude estimate to find the runs worth a closer
look.</p>

<h4>openEMS</h4>
{img:openems}
<p>3D electromagnetic simulation (FDTD) of the selected line with openEMS,
in a separate window. Results: S11, S21, impedance (results.png),
TDR/TDT with the chosen <i>rise time</i> and, with <i>Save fields</i> on, field
GIFs (top view, cross-section, energy) at the chosen <i>voltage</i>.
<i>Reprocess</i> redoes GIFs and TDR without re-simulating.
Bandwidth rule: f max &gt;= 1.2 / rise time.
Python, openEMS folder, results folder and mesh: Options tab.</p>

<h4>Installing openEMS</h4>
<p>The Plugin Manager installs only the plugin: openEMS must be installed
separately (it is needed only by the openEMS tab).</p>
<ol>
<li>Download openEMS for Windows from the official openEMS releases and
extract the archive into a folder (e.g. <tt>D:\\Programs\\openEMS</tt>).</li>
<li>Install a 64-bit Python (a version supported by the modules of that
openEMS release).</li>
<li>In <b>Options</b> set the Python and the openEMS folder, then press
<b>Check openEMS</b>: it checks everything and tells what is missing.</li>
<li>If numpy, h5py or matplotlib are missing, or the CSXCAD/openEMS modules
(installed from the .whl files in the openEMS folder), the
<b>Install missing packages</b> button installs them after confirmation.
Then press Check again.</li>
</ol>

<h4>Options</h4>
<p>Language, stackup (Er and dielectric: <i>auto</i> = from the board), ground
net, solder mask, DC current parameters and openEMS paths. Keep the results
folders outside OneDrive.</p>

<h4>Limits to keep in mind</h4>
<ul>
<li>The analyses are quasi-static (except openEMS): useful to compare and
find problems, not a replacement for measurements.</li>
<li>With <i>Zones = zero resistance</i> the DC current is optimistic; without
it, pessimistic.</li>
</ul>
"""


def page(lang):
    """
    Pagina HTML dell'aiuto nella lingua scelta ("it" o "en"). I segnaposto
    {img:nome} diventano le immagini di gui/img (nome_it.png / nome_en.png),
    disegni che mostrano su cosa lavora ogni scheda e i dati da inserire.
    """
    import os
    import re

    html = _EN if lang == "en" else _IT
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")

    def img_tag(m):
        path = os.path.join(img_dir, f"{m.group(1)}_{'en' if lang == 'en' else 'it'}.png")
        if not os.path.exists(path):
            return ""  # immagine mancante: si mostra solo il testo
        # wx.html vuole un percorso con le barre "/" anche su Windows
        return f'<p><img src="{path.replace(os.sep, "/")}" width="600"></p>'

    return re.sub(r"\{img:(\w+)\}", img_tag, html)


def section(lang, key):
    """
    Solo la sezione di una scheda (titolo, disegno e testo), per il
    pulsante "?" delle schede. key = nome dell'immagine (es. "impedance").
    """
    import re

    full = page(lang)
    # La sezione inizia col titolo <h4> che precede l'immagine della scheda
    # e finisce al titolo <h4> successivo
    m = re.search(r"(<h4>[^<]*</h4>\s*<p><img [^>]*/%s_\w+\.png[^>]*></p>.*?)(?=<h4>|$)" % key,
                  full, re.S)
    return m.group(1) if m else full
