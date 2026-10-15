# -*- coding: utf-8 -*-
"""
Text of the "Help" tab (simple HTML for wx.html), in Italian and English.
page(lang) returns the page in the chosen language.
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
<p><i>Analizza</i> controlla tutte le tracce; <i>Analizza selezione</i> solo
quelle selezionate in Pcbnew (la finestra del plugin resta aperta: clicca la
traccia sulla board, il tasto <b>U</b> seleziona tutta la traccia collegata).
<i>Evidenzia tutte</i> seleziona in Pcbnew tutte le tracce della lista.</p>
<p><b>Mappa della corrente di ritorno</b>: mostra dove scorre nella massa la
corrente che torna indietro da una linea.</p>
<ol>
<li>Seleziona in Pcbnew il pad (o una traccia) da cui entra la corrente e premi
<i>Ingresso da selezione</i>.</li>
<li>In <i>Uscita ritorno</i> scegli il pad di massa dove colleghi la massa
dell'alimentatore o dello strumento (elenco dei GND di connettori e test point,
oppure selezionalo e premi <i>Uscita da selezione</i>); "automatica" usa i pin
GND del componente di ingresso.</li>
<li>Scegli la <i>Frequenza</i> e la <i>Risoluzione</i> (Alta e Molto alta: disegno
piu' fine, calcolo circa 3 e 7 volte piu' lungo) e premi <i>Mappa ritorno</i>.</li>
<li>Controlla la tabella dei carichi e premi OK.</li>
</ol>
<p><b>Carichi</b>: il plugin trova da solo la net e i componenti con un pin di
massa raggiunti dall'ingresso, anche oltre resistenze, ferriti e altri
componenti in serie. La corrente di ognuno e' <b>stimata</b> dal tipo e dal valore:
TVS e zener 0 (non conducono); resistenza V/R; condensatore V/|Z| alla frequenza
scelta (0 in DC); gate di un MOSFET quasi 0; base di un BJT (V-0,7)/R in serie;
collettore o drain V/(R in serie + pull-up), cioe' con il transistor acceso;
ingresso di un chip 1 uA; i casi non riconosciuti 1 mA di prova. La funzione
del pin di un transistor si legge dal nome del pin (es. "C-3"), dal numero del
pad o dal nome della net ("Net-(Q1-C)"). La colonna <i>Stima</i> dice come e'
stato ottenuto ogni valore.</p>
<p><b>Tensione</b>: si legge dal nome della net (VCC_3.3, 5V, 3V3); se manca si
cerca risalendo per resistenze, induttanze e ferriti (es. un pull-up verso
VCC_5V) o fra le net del componente di ingresso: e' la tensione di
alimentazione, cioe' un limite superiore. Se non si trova si ipotizzano 3,3 V
e il campo si colora: scrivi quella vera e premi <i>Ricalcola stima</i>. Con soli
resistori e condensatori la tensione non cambia le percentuali.</p>
<p><b>Spunta</b>: con la spunta il carico entra nella mappa (percorso, corrente e
ritorno dai suoi pin GND); senza e' come se non ci fosse. Le quote si dividono
fra i carichi spuntati in proporzione alla corrente: togliendo il carico
maggiore, gli altri salgono. Una riga con corrente 0 e' ignorata anche se
spuntata. Il risultato resta <b>teorico</b>: non e' una simulazione del circuito.</p>
<p><b>Pin di massa</b>: la quota di ogni carico entra dai suoi pin GND (per un pin
SMD che non tocca il piano si usa la via di massa piu' vicina, entro 3 mm). I
pin GND di uno stesso componente sono collegati fra loro come da una massa
interna comune: il calcolo fa uscire piu' corrente dai pin con la strada piu'
facile verso l'uscita. Le etichette "GND xx%" danno la quota di ogni pin sul
totale. Come il chip distribuisca davvero la corrente fra i pin dipende dal
suo interno e non e' noto.</p>
<p><b>Alta frequenza (HF)</b>: il ritorno segue la traccia (induttanza minima).
<b>Continua (DC)</b>: il ritorno prende la strada a resistenza minima verso
l'uscita, anche lontano dalla traccia (utile per vedere se correnti di potenza
passano sotto un segnale); i condensatori non sono carichi e un condensatore in
serie blocca la corrente. Il calcolo considera piani, massa complanare accanto
alle tracce e zone di massa su altri layer, collegate dalle via di massa. Dove
il segnale cambia layer il ritorno deve passare da un piano all'altro: con una
via di massa vicina passa da li', senza passa per la capacita' fra i piani
(rumore ed emissioni).</p>
<p><b>Finestra della mappa</b>: si sceglie il layer da vedere. Colore = intensita'
(in HF % del picco ideale, in DC % del massimo); le frecce danno solo il verso,
per l'intensita' guardare il colore. Le via di massa piu' cariche mostrano la
loro quota. Le caselle <i>Componenti</i> (contorno, sigla, pad: verdi quelli di
massa) e <i>Altre tracce</i> (tracce delle altre net, in trasparenza) servono a
orientarsi e non cambiano il calcolo. E' una stima quasi-statica; per il
risultato completo usare openEMS.</p>

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
<p><i>Analyze</i> checks all the tracks; <i>Analyze selection</i> only the
ones selected in Pcbnew (the plugin window stays open: click the track on
the board, the <b>U</b> key selects the whole connected track).
<i>Highlight all</i> selects in Pcbnew all the tracks of the list.</p>
<p><b>Return current map</b>: shows where the current returning from a line
flows in the ground.</p>
<ol>
<li>Select in Pcbnew the pad (or a track) where the current enters and press
<i>Input from selection</i>.</li>
<li>In <i>Return exit</i> choose the ground pad where the supply or instrument
ground is connected (list of connector and test point GND pads, or select it
and press <i>Exit from selection</i>); "automatic" uses the GND pins of the
input component.</li>
<li>Choose the <i>Frequency</i> and the <i>Resolution</i> (High and Very high: finer
drawing, about 3 and 7 times longer calculation) and press <i>Return map</i>.</li>
<li>Check the loads table and press OK.</li>
</ol>
<p><b>Loads</b>: the plugin finds by itself the net and the components with a
ground pin reached from the input, also beyond resistors, ferrites and other
series parts. The current of each one is <b>estimated</b> from its type and value:
TVS and zener 0 (they do not conduct); resistor V/R; capacitor V/|Z| at the
chosen frequency (0 in DC); MOSFET gate almost 0; BJT base (V-0.7)/series R;
collector or drain V/(series R + pull-up), i.e. with the transistor on; chip
input 1 uA; unrecognized cases 1 mA as a placeholder. The pin function of a
transistor is read from the pin name (e.g. "C-3"), the pad number or the net
name ("Net-(Q1-C)"). The <i>Estimate</i> column tells how each value was
obtained.</p>
<p><b>Voltage</b>: read from the net name (VCC_3.3, 5V, 3V3); if missing it is
searched through resistors, inductors and ferrites (e.g. a pull-up to VCC_5V)
or among the nets of the input component: it is the supply voltage, i.e. an
upper limit. If nothing is found 3.3 V is assumed and the field is
highlighted: write the real one and press <i>Recalculate estimate</i>. With only
resistors and capacitors the voltage does not change the percentages.</p>
<p><b>Checkbox</b>: checked, the load enters the map (path, current and return
from its GND pins); unchecked, it is as if it were not there. The shares are
split among the checked loads in proportion to their current: removing the
largest load, the others rise. A row with zero current is ignored even if
checked. The result stays <b>theoretical</b>: it is not a circuit simulation.</p>
<p><b>Ground pins</b>: the share of each load enters through its GND pins (for an
SMD pin not touching the plane the nearest ground via within 3 mm is used).
The GND pins of the same part are joined as by a common internal ground: the
calculation lets more current leave from the pins with the easiest path to the
exit. The "GND xx%" labels give the share of each pin on the total. How the
chip really splits the current among its pins depends on its inside and is not
known.</p>
<p><b>High frequency (HF)</b>: the return follows the track (minimum inductance).
<b>DC</b>: the return takes the minimum-resistance path to the exit, even far
from the track (useful to see whether power currents flow under a signal);
capacitors are not loads and a series capacitor blocks the current. The
calculation includes planes, coplanar ground next to the tracks and ground
zones on other layers, joined by the ground vias. Where the signal changes
layer the return must move between planes: with a ground via nearby it goes
through it, otherwise through the capacitance between the planes (noise and
emissions).</p>
<p><b>Map window</b>: choose the layer to view. Color = intensity (HF: % of the
ideal peak, DC: % of the maximum); the arrows give only the direction, for the
intensity look at the color. The most loaded ground vias show their share. The
<i>Components</i> (outline, reference, pads: green the ground ones) and <i>Other
tracks</i> (tracks of the other nets, semi-transparent) checkboxes help to find
your way and do not change the calculation. It is a quasi-static estimate; for
the full result use openEMS.</p>

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
    HTML help page in the chosen language ("it" or "en"). The {img:name}
    placeholders become the images in gui/img (name_it.png / name_en.png):
    drawings showing what each tab works on and which data to enter.
    """
    import os
    import re

    html = _EN if lang == "en" else _IT
    img_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")

    def img_tag(m):
        path = os.path.join(img_dir, f"{m.group(1)}_{'en' if lang == 'en' else 'it'}.png")
        if not os.path.exists(path):
            return ""  # missing image: only the text is shown
        # wx.html wants a path with "/" separators, even on Windows
        return f'<p><img src="{path.replace(os.sep, "/")}" width="600"></p>'

    return re.sub(r"\{img:(\w+)\}", img_tag, html)


def section(lang, key):
    """
    Only the section of one tab (title, drawing and text), for the "?" button
    of the tabs. key = name of the image (e.g. "impedance").
    """
    import re

    full = page(lang)
    # The section starts with the <h4> title preceding the tab's image and ends
    # at the next <h4> title
    m = re.search(r"(<h4>[^<]*</h4>\s*<p><img [^>]*/%s_\w+\.png[^>]*></p>.*?)(?=<h4>|$)" % key,
                  full, re.S)
    return m.group(1) if m else full
