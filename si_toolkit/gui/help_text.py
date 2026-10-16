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

<h4>Controlli layout</h4>
{img:layout_check}
<p>Un DRC "ragionato" su <b>tutta la scheda</b>: misura il layout e confronta le
misure con soglie di buona pratica. Non prevede grandezze fisiche: ogni riga e'
un fatto (una distanza, una via che manca), con la misura trovata e il limite.
Prima dei controlli riempi le zone (tasto <b>B</b>). I pulsanti <i>Tutti</i> e <i>Nessuno</i> selezionano o tolgono tutti i controlli in un colpo. Sono masse tutte le net il
cui nome contiene il testo di <b>Opzioni</b> &gt; Net di massa (con "GND": GND,
AGND, DGND, PGND...), ma ogni massa resta separata: una via, un piano o un
condensatore contano solo per la propria net.</p>
<ul>
<li><b>Disaccoppiamento</b>: per ogni pin di alimentazione degli integrati (U, IC)
il condensatore (C) piu' vicino fra quella net e la massa dell'integrato (la net
dei suoi pin GND: un condensatore verso AGND non vale per un chip su DGND).
I pin non collegati a nulla sono ignorati. Oltre la soglia di <i>attenzione</i> la riga e' gialla, oltre quella
di <i>errore</i> rossa; un pin senza alcun condensatore e' sempre un errore. Poi,
per il condensatore trovato e per i pin GND SMD degli integrati, una via di massa
collegata al piano entro la soglia indicata. Un pin e' di alimentazione se nello
schema e' di tipo <i>power input</i>, oppure (pin passivo o senza tipo) se il nome
della net lo indica: +3V3, 5V, VCC, VDD, VBAT...</li>
<li><b>Cambio layer</b>: una via di segnale dove la traccia passa su un layer con
un piano di riferimento diverso (es. due layer: sopra la traccia guarda il piano
sotto, sotto guarda quello sopra). Il ritorno deve saltare da un piano all'altro:
serve una via di massa, collegata a entrambi i piani, entro la soglia (oltre il
doppio e' un errore). Se i due piani sono masse diverse (GND e AGND) nessuna via
puo' collegarli: e' sempre un errore. Con la spunta si ignorano le net di
alimentazione.</li>
<li><b>Via di stitching</b>: solo con la massa su due o piu' layer. Ogni punto della
massa deve stare vicino a una via della stessa massa che tocca lo stesso pezzo
di rame, come se le via formassero una griglia con il <i>passo massimo</i>
indicato. Con <i>Distingui le isole di rame</i> una via oltre una fessura, su un
altro pezzo di rame, non conta: un'isola senza via e' sempre un errore. Le zone che non lo
rispettano diventano una riga (area in mm2, via piu' vicina) e una <b>forma piena</b>
sulla scheda che copre tutta l'area: per correggere basta mettere una o piu' via
di massa dentro la forma e rifare i controlli. <i>Misura</i> = distanza del punto
piu' lontano dell'area dalla via di massa piu' vicina; <i>Limite</i> = distanza
massima ammessa, cioe' il passo diviso 1,41 (7,1 mm con passo 10 mm: e' il punto
piu' lontano di una griglia di via con quel passo). Come riferimento per il passo:
lambda/20 alla
frequenza piu' alta in gioco, circa 15 mm a 500 MHz e 7,5 mm a 1 GHz in FR4.</li>
<li><b>Piano interrotto</b>: il controllo della scheda Return Path su tutte le
tracce (gap del piano sotto la traccia piu' lungo del <i>Gap minimo</i>).</li>
<li><b>Bordo del piano</b>: sotto una traccia il rame di massa del layer
adiacente deve continuare, oltre il bordo della traccia, per almeno N volte
<b>h</b>, lo spessore del dielettrico fra traccia e piano (dallo stackup; N = 3
predefinito). Il campo della traccia si allarga di qualche h ai lati: dove il
piano finisce prima, una parte del campo e della corrente di ritorno resta senza
piano (piu' emissioni e crosstalk).
<br><i>Misura</i> = distanza, vista dall'alto, dal <b>bordo della traccia</b> al
punto dove <b>finisce il rame di massa</b> sul layer adiacente. Attenzione: il rame
si ferma prima del bordo della scheda (distanza rame-bordo delle regole, di solito
0,5 mm), quindi dal bordo della scheda la traccia deve stare circa 0,5 mm in piu'.
<br><i>Limite</i> = N x h. Sotto 1 h e' un errore, fra 1 h e N x h un avviso.
<br>Sulla scheda, oltre al cerchio, c'e' il <b>segmento misurato</b> con il valore:
mostra da dove a dove si e' misurato. Non sono un bordo del piano i fori attorno a
via e pad (anche quelli grandi dei pin dei connettori) e i tagli stretti, fino a
2 mm, che le tracce del layer del piano fanno nella massa: su un due layer sono
ovunque. Non si segnalano i tratti piu' corti del limite (una traccia che arriva di
traverso a un pin vicino al bordo) ne' quelli dove la traccia esce dal piano, che
sono del controllo <i>Piano interrotto</i>.
{img:lc_plane_edge}</li>
<li><b>Larghezza tracce</b>: per le net scritte nel campo <i>Correnti</i>
(es. <tt>+5V=2; VIN=3</tt>, ammessi * e ?) ogni traccia si confronta con la
larghezza che la formula IPC-2221 chiede per quella corrente, con il rame del suo
layer preso dallo stackup (35 um se manca).
<br><i>Misura</i> = larghezza attuale della traccia. <i>Limite</i> = larghezza
necessaria per non superare il <i>Riscaldamento massimo</i>. Il dettaglio dice anche
il riscaldamento stimato; oltre il doppio del massimo e' un errore. Una riga per
net, layer e larghezza: cliccandola si selezionano tutti i tratti.
{img:lc_width}</li>
<li><b>Isolamento</b>: fra due net la cui tensione differisce di oltre
30 V si cerca il punto piu' vicino sullo stesso layer (tracce, pad, via e zone).
<br><i>Misura</i> = distanza da bordo a bordo del rame. <i>Limite</i> = distanza
della tabella IPC-2221 per quella differenza di tensione: B2 sui layer esterni senza
rivestimento, B1 su quelli interni (vedi il disegno). Sotto il limite e' un errore.
<br>La tensione di una net e' quella del campo <i>Tensioni</i>, altrimenti 0 V per le
masse e quella scritta nel nome (+5V, 24V_IN, 3V3, -12V). Le net senza tensione nota
non si controllano: quelle vicine a una net oltre 30 V sono elencate nella riga di
stato, cosi' puoi scriverne la tensione.
{img:lc_isolation}</li>
<li><b>Lunghezze</b>: le <b>coppie differenziali</b> si riconoscono dai nomi
(_P/_N, DP/DM, +/-); i <b>gruppi</b> si scrivono nel campo <i>Gruppi di
lunghezza</i> (es. <tt>SD_*; ETH_TX*, ETH_CLK</tt>: un gruppo per ';', nomi separati
da ','). La lunghezza di una net e' quella di tutte le sue tracce piu' l'altezza
attraversata nelle via.
<br>Coppie: <i>Misura</i> = differenza fra le due lunghezze (skew), <i>Limite</i> =
<i>Skew massimo</i>; il dettaglio dice quale delle due allungare. Gruppi:
<i>Misura</i> = quanto la net e' piu' corta della piu' lunga del gruppo,
<i>Limite</i> = <i>Differenza massima</i>. Oltre il doppio del limite e' un errore.
{img:lc_length}</li>
<li><b>Rami morti</b>: tracce che finiscono senza collegarsi a niente (nessuna
altra traccia, pad, via o zona della stessa net tocca l'estremita'). Il ramo
morto si segue all'indietro fino al primo incrocio. <i>Misura</i> = lunghezza del
ramo morto, <i>Limite</i> = <i>Rami morti da</i>; oltre 5 volte e' un errore. Il
rame che non porta a niente fa da antenna e, su una linea veloce, e' uno stub che
riflette il segnale. Due tracce sono collegate se il rame si tocca, come per KiCad,
anche se le estremita' non coincidono esattamente.
{img:lc_stub}</li>
<li><b>Angoli acuti</b>: due tratti della stessa net, sullo stesso layer, che si
incontrano con un angolo piu' piccolo del limite (anche una traccia che si innesta
di fianco su un'altra). Nella punta stretta l'acido di incisione ristagna e puo'
mangiare il rame (acid trap). <i>Misura</i> = angolo, <i>Limite</i> = <i>Angoli
acuti sotto</i>. Non contano gli angoli dentro un pad, i micro-tratti piu' corti
della loro larghezza (resti delle modifiche) e due tratti sovrapposti.
{img:lc_acute}</li>
<li><b>Cambi di larghezza</b>: una net di segnale con tracce di larghezze diverse
sullo stesso layer: ogni larghezza e' un'impedenza, ogni cambio un piccolo salto.
<i>Misura</i> = (larga - stretta) / stretta in %, <i>Limite</i> = <i>Cambio di
larghezza oltre</i>; oltre il doppio e' un errore. Le strozzature vicino ai pad
(tratti fino a 1 mm che finiscono su un pad) non contano. Il dettaglio dice le
larghezze e quanti mm di traccia ha ciascuna.
{img:lc_width_step}</li>
<li><b>Via nei pad</b>: il foro di una via dentro un pad SMD. In saldatura lo stagno
scende nel foro e la saldatura resta senza: sposta la via fuori dal pad, oppure
chiedi al produttore via-in-pad riempite e chiuse. I pad grandi (oltre 1,5 mm su
entrambi i lati, cioe' i pad termici dei QFN) non contano: li' le via si mettono
apposta.
{img:lc_via_in_pad}</li>
<li><b>Tombstoning</b>: componenti piccoli a due pad (da 0201 a 0805, diodi
SOD-323/523) con un pad annegato in una zona con collegamento pieno e l'altro
collegato solo da tracce. In saldatura il pad nella zona si scalda piu' tardi:
l'altro lato fonde prima e tira su il componente. Si risolve con lo scarico
termico (thermal relief) sul pad nella zona. Il controllo guarda il rame attorno
al pad: se lo circonda tutto e' "annegato".
{img:lc_tombstone}</li>
<li><b>Corrente via</b>: per le net del campo <i>Correnti</i>, le via vicine fra loro
(entro 3 mm) sono un cambio di layer che porta tutta la corrente della net.
<i>Misura</i> = via presenti, <i>Limite</i> = via necessarie per il
<i>Riscaldamento massimo</i>, con la formula IPC-2221 sulla canna della via
(placcatura dalla scheda <b>Opzioni</b>, come la scheda Corrente DC). Errore se ogni
via si scalderebbe piu' del doppio del massimo.
{img:lc_via_current}</li>
<li><b>Quarzo</b>: per ogni quarzo (riferimento Y, o "Crystal" nel nome del
footprint) due controlli. Tracce di altre net sotto il quarzo, su qualunque layer:
portano disturbi in un circuito molto sensibile (errore). Lunghezza delle tracce
fra il quarzo e l'integrato, condensatori di carico compresi: <i>Misura</i> =
lunghezza, <i>Limite</i> = <i>Tracce quarzo-integrato fino a</i>.
{img:lc_crystal}</li>
<li><b>Tracce sovrapposte</b>: tracce di due net diverse una sopra l'altra (il rame
si sovrappone visto dall'alto) su layer adiacenti, senza un piano in mezzo: si
accoppiano molto (crosstalk). <i>Misura</i> = lunghezza del tratto sovrapposto,
<i>Limite</i> = <i>Tracce sovrapposte da</i>; oltre 4 volte e' un errore.
{img:lc_broadside}</li>
</ul>
<p><b>Escludere una riga</b>: un avviso valutato e accettato (per esempio una
traccia lenta vicino al bordo) si esclude con il <b>clic destro</b> sulla riga,
<i>Escludi (accettato)</i>. La riga diventa grigia e va in fondo alla tabella, come
fa KiCad con gli errori esclusi del DRC: non conta negli errori e negli avvisi e non
viene disegnata sulla scheda. Resta esclusa anche nei controlli successivi, finche'
non modifichi gli oggetti coinvolti (la riga e' riconosciuta da loro). Con il clic
destro si include di nuovo, una o tutte.</p>
{img:lc_exclude}
<p><b>Dati di ogni scheda</b>: le righe escluse e i <i>Dati delle net</i> (correnti,
tensioni, gruppi) si salvano in un piccolo file accanto alla scheda,
<tt>nome_scheda.si_toolkit.json</tt>: ogni scheda ha i suoi. Le soglie invece sono le
stesse per tutte le schede. Una scheda mai salvata non ha ancora un file: le
esclusioni valgono finche' la finestra resta aperta.</p>
<p><b>Rapporto</b>: dopo i controlli, <i>Rapporto...</i> crea una pagina HTML accanto
alla scheda (<tt>nome_scheda_controlli_layout.html</tt>) e la apre nel browser: data,
versione, soglie e dati usati, riepilogo per controllo, disegno della scheda con i
problemi numerati e, per ogni problema, il testo, la misura, il limite, la posizione
e un ingrandimento della scheda in quel punto. Le righe escluse sono in fondo, in
grigio. Per il PDF: dal browser <i>Stampa</i> -> <i>Salva come PDF</i>.</p>
{img:lc_report}
<p><b>Scheda di prova</b>: nel repository, in <tt>docs/test_board</tt>, c'e' una
scheda con un caso per ciascuno dei 16 controlli (e il suo file con i dati delle
net). Aprila e lancia i controlli per vedere come funzionano, o per verificare il
plugin dopo un aggiornamento di KiCad; il file <tt>README.md</tt> della cartella
elenca le righe attese.</p>
<p><b>Distanze</b>: fra pad e via, fra pin e condensatore e fra due via si misura
da bordo di rame a bordo di rame (lo spazio libero fra i due), non da centro a
centro. Per le via di stitching si misura dal punto della massa al centro della
via, come il passo di una griglia.</p>
<p><b>Sulla scheda</b>, sul layer <b>User.1</b> per gli errori e <b>User.2</b> per
gli avvisi: un cerchio centrato su ogni problema (il pin, la via, la traccia) e,
per le via di stitching, una forma piena che copre l'area troppo lontana dalle
via (la forma segue la griglia del controllo, quindi ha i bordi a gradini). Sopra
la forma c'e' la misura: una croce sul punto piu' lontano, un segmento fino alla
via usata per il calcolo (cerchiata) e la distanza scritta, la stessa della
colonna <i>Misura</i>. Se
la forma copre troppo, nel pannello Aspetto di Pcbnew puoi abbassare l'opacita'
dei layer User. Cliccando una riga si
selezionano anche in Pcbnew gli oggetti coinvolti e la vista si centra su di
essi; per un'area di stitching la vista si centra sulla forma e la evidenzia. Se la stessa zona e' lontana
dalle via su piu' layer, e' una riga sola con tutti i layer (es. F.Cu + B.Cu). <i>Pulisci overlay</i> toglie tutto; <i>Mostra</i> filtra la tabella.</p>
<p><b>Valori predefiniti</b> (regole di buona pratica per una scheda generica,
logica digitale fino a qualche centinaio di MHz; il pulsante <i>Valori
predefiniti</i> li rimette):</p>
<ul>
<li>condensatore entro 3 mm dal pin (attenzione), 8 mm (errore): oltre una decina
di mm un 100 nF disaccoppia poco; per integrati veloci meglio 1-2 mm;</li>
<li>via di massa entro 1 mm dal pad GND: di solito la via sta subito accanto al pad;</li>
<li>via di ritorno entro 2 mm dalla via di segnale (errore oltre 4 mm);</li>
<li>via di stitching ogni 10 mm, circa lambda/20 a 750 MHz in FR4. Per zone RF
serve meno: con il GNSS a 1,5 GHz circa 5 mm;</li>
<li>gap del piano da 5 mm: quelli piu' corti sono gli attraversamenti delle
tracce dell'altro lato, inevitabili su due layer. Per linee RF anche 1-2 mm
contano;</li>
<li>bordo del piano a 3 h dalla traccia: entro 3 h sta quasi tutto il campo.
Su un due layer da 1,6 mm (h circa 1,5 mm) sono circa 4,5 mm, quindi anche le
tracce a pochi mm dal bordo della scheda vengono segnalate: per segnali lenti
puoi alzare la soglia o ignorarle;</li>
<li>riscaldamento delle tracce 10 C (errore oltre 20 C);</li>
<li>skew delle coppie 0,5 mm. Valori tipici: USB 2.0 circa 1,25 mm, Ethernet
100 Mbit circa 1,3 mm, HDMI e PCIe 0,1-0,15 mm;</li>
<li>differenza nei gruppi 2 mm (es. bus SD/SDIO); per DDR servono pochi decimi;</li>
<li>rami morti da 1 mm (errore oltre 5 mm), angoli acuti sotto 90 gradi, cambi di
larghezza oltre il 25 %, tracce quarzo-integrato fino a 10 mm, tracce sovrapposte da
5 mm.</li>
</ul>
<p><b>Limiti</b> da tenere presenti:</p>
<ul>
<li>Il condensatore considerato e' il <b>piu' vicino</b> sulla stessa
alimentazione, senza guardarne il valore: un elettrolitico da 10 uF vicino al
pin fa passare il controllo anche se il 100 nF e' lontano.</li>
<li>Il cambio layer controlla <b>tutti i segnali</b>, anche quelli lenti (I2C,
pulsanti, LED) per cui la via di ritorno non serve: molti avvisi gialli possono
essere trascurati. Le net di alimentazione si escludono con la casella.</li>
<li>Il passo delle via di stitching e' <b>uno solo per tutta la scheda</b>: per una
zona RF piu' esigente fai un secondo controllo con un passo piu' piccolo e
guarda solo quella zona.</li>
<li>Si considerano solo i piani di massa: un piano di alimentazione usato come
riferimento non conta.</li>
<li>Le distanze sono in linea d'aria, non lungo le tracce.</li>
<li>Le aree di stitching seguono una griglia di 1-2 mm: i bordi delle forme sono
indicativi, non esatti.</li>
<li>Le isole di rame si leggono dai poligoni del riempimento: se questa versione
di KiCad non li fornisce, i controlli continuano senza distinguere le isole e lo
dicono nella riga di stato.</li>
<li>Larghezza tracce: si assume <b>tutta la corrente</b> della net su ogni
traccia, quindi anche un ramo sottile verso un piccolo carico viene segnalato. La
distribuzione reale si vede nella scheda <b>Corrente DC</b>, che controlla anche
le via. La formula IPC-2221 e' empirica, per tracce isolate.</li>
<li>Isolamento: le distanze IPC-2221 sono un minimo di progetto del circuito
stampato. Per apparecchi collegati alla rete le norme di sicurezza (IEC 62368-1,
IEC 60664) chiedono distanze in aria e superficiali (creepage) piu' grandi, che
dipendono dal tipo di isolamento. Si misura solo sullo stesso layer.</li>
<li>Lunghezze: su una net con diramazioni la lunghezza comprende tutti i rami,
come il Net Inspector di KiCad.</li>
<li>Cambi di larghezza, rami morti, angoli acuti e tracce sovrapposte guardano
<b>tutte le net di segnale</b>, anche quelle lente, per cui contano poco: le net di
alimentazione si escludono con la casella. Il quarzo si riconosce solo dal
riferimento Y o dal nome del footprint.</li>
</ul>

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
per l'intensita' guardare il colore; con <i>Frecce in movimento</i> scorrono nel
verso della corrente, piu' veloci dove e' piu' forte. Le via di massa piu' cariche mostrano la
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

<h4>Layout checks</h4>
{img:layout_check}
<p>A "smart" DRC on the <b>whole board</b>: it measures the layout and compares
the measures with good-practice thresholds. It does not predict physical
quantities: every row is a fact (a distance, a missing via), with the measure
found and the limit. Fill the zones (<b>B</b> key) before the checks. The <i>All</i> and <i>None</i> buttons select or clear all the checks at once. Grounds are all
the nets whose name contains the text of <b>Options</b> &gt; Ground net (with
"GND": GND, AGND, DGND, PGND...), but each ground stays separate: a via, a plane
or a capacitor counts only for its own net.</p>
<ul>
<li><b>Decoupling</b>: for every supply pin of the integrated circuits (U, IC)
the nearest capacitor (C) between that net and the IC's ground (the net of its
GND pins: a capacitor to AGND does not count for a chip on DGND). Pins
not connected to anything are ignored. Beyond the <i>warning</i> threshold the row is yellow,
beyond the <i>error</i> one red; a pin with no capacitor at all is always an
error. Then, for the capacitor found and for the SMD GND pins of the ICs, a
ground via connected to the plane within the given threshold. A pin is a supply
pin if its schematic type is <i>power input</i>, or (passive or untyped pin) if
the net name says so: +3V3, 5V, VCC, VDD, VBAT...</li>
<li><b>Layer change</b>: a signal via where the track moves to a layer with a
different reference plane (e.g. two layers: on top the track sees the bottom
plane, on the bottom it sees the top one). The return has to jump from one plane
to the other: a ground via connected to both planes is needed within the
threshold (beyond twice as much it is an error). If the two planes are
different grounds (GND and AGND) no via can join them: it is always an error.
The check box skips supply nets.</li>
<li><b>Stitching vias</b>: only with ground on two or more layers. Every point of
the ground must be close to a via of the same ground touching the same piece of
copper, as if the vias formed a grid with the given <i>maximum spacing</i>.
With <i>Distinguish copper islands</i> a via across a slot, on another piece of
copper, does not count: an island with no via is always an error. The areas that do not
comply become a row (area in mm2, nearest via) and a <b>filled shape</b> on the
board covering the whole area: to fix it, place one or more ground vias inside
the shape and run the checks again.
<i>Measured</i> = distance of the farthest point of the area from the nearest
ground via; <i>Limit</i> = maximum allowed distance, that is the spacing divided
by 1.41 (7.1 mm with a 10 mm spacing: the farthest point of a grid of vias with
that spacing). As a reference for the spacing: lambda/20 at the
highest frequency involved, about 15 mm at 500 MHz and 7.5 mm at 1 GHz in
FR4.</li>
<li><b>Plane gap</b>: the Return Path tab check on all the tracks (gap of the
plane under the track longer than the <i>Minimum gap</i>).</li>
<li><b>Plane edge</b>: under a track the ground copper of the adjacent
layer must go on, beyond the edge of the track, for at least N times <b>h</b>,
the dielectric height between track and plane (from the stackup; N = 3 by
default). The field of the track spreads a few h to the sides: where the plane
ends earlier, part of the field and of the return current has no plane under it
(more emissions and crosstalk).
<br><i>Measured</i> = distance, seen from above, from the <b>edge of the track</b>
to the point where the <b>ground copper ends</b> on the adjacent layer. Note: the
copper stops before the board edge (copper-to-edge clearance of the rules,
usually 0.5 mm), so from the board edge the track must stay about 0.5 mm more.
<br><i>Limit</i> = N x h. Below 1 h it is an error, between 1 h and N x h a warning.
<br>On the board, besides the circle, there is the <b>measured segment</b> with its
value: it shows where the measure goes from and to. These are not a plane edge:
the holes around vias and pads (also the large ones of connector pins) and the
narrow cuts, up to 2 mm, that the tracks of the plane layer make in the ground:
on a two-layer board they are everywhere. Stretches shorter than the limit (a
track reaching a pin near the edge) are not reported, nor the ones where the
track leaves the plane, which belong to the <i>Plane gap</i> check.
{img:lc_plane_edge}</li>
<li><b>Track width</b>: for the nets typed in the <i>Currents</i> field
(e.g. <tt>+5V=2; VIN=3</tt>, * and ? allowed) every track is compared with the
width the IPC-2221 formula asks for that current, with the copper of its layer
taken from the stackup (35 um if missing).
<br><i>Measured</i> = actual width of the track. <i>Limit</i> = width needed not to
exceed the <i>Maximum temperature rise</i>. The detail also gives the estimated
rise; beyond twice the maximum it is an error. One row per net, layer and width:
clicking it selects all the segments.
{img:lc_width}</li>
<li><b>Isolation</b>: between two nets whose voltages differ by more than
30 V the closest point on the same layer is searched (tracks, pads, vias and
zones).
<br><i>Measured</i> = copper edge-to-edge distance. <i>Limit</i> = distance of the
IPC-2221 table for that voltage difference: B2 on the outer layers without
coating, B1 on the inner ones (see the drawing). Below the limit it is an error.
<br>The voltage of a net is the one of the <i>Voltages</i> field, otherwise 0 V for
the grounds and the one written in the name (+5V, 24V_IN, 3V3, -12V). Nets with
an unknown voltage are not checked: the ones close to a net above 30 V are listed
in the status line, so you can type their voltage.
{img:lc_isolation}</li>
<li><b>Lengths</b>: the <b>differential pairs</b> are recognized from the
names (_P/_N, DP/DM, +/-); the <b>groups</b> are typed in the <i>Length groups</i>
field (e.g. <tt>SD_*; ETH_TX*, ETH_CLK</tt>: one group per ';', names separated by
','). The length of a net is that of all its tracks plus the height crossed in
the vias.
<br>Pairs: <i>Measured</i> = difference between the two lengths (skew),
<i>Limit</i> = <i>Maximum skew</i>; the detail says which one to lengthen. Groups:
<i>Measured</i> = how much the net is shorter than the longest of the group,
<i>Limit</i> = <i>Maximum difference</i>. Beyond twice the limit it is an error.
{img:lc_length}</li>
<li><b>Dead branches</b>: tracks ending without connecting to anything (no other
track, pad, via or zone of the same net touches the end). The dead branch is
followed back to the first junction. <i>Measured</i> = length of the dead branch,
<i>Limit</i> = <i>Dead branches from</i>; beyond 5 times it is an error. Copper
leading nowhere acts as an antenna and, on a fast line, is a stub that reflects
the signal. Two tracks are connected when their copper touches, as for KiCad, even
if their ends do not coincide exactly.
{img:lc_stub}</li>
<li><b>Acute angles</b>: two segments of the same net, on the same layer, meeting
at an angle smaller than the limit (also a track joining another one from the
side). In the narrow tip the etching liquid stays and can eat the copper (acid
trap). <i>Measured</i> = angle, <i>Limit</i> = <i>Acute angles below</i>. Angles
inside a pad, micro segments shorter than their width (left by editing) and two
overlapping segments are not counted.
{img:lc_acute}</li>
<li><b>Width steps</b>: a signal net with tracks of different widths on the same
layer: every width is an impedance, every change a small step.
<i>Measured</i> = (wide - narrow) / narrow in %, <i>Limit</i> = <i>Width step
above</i>; beyond twice it is an error. Neck-downs at the pads (segments up to
1 mm ending on a pad) are not counted. The detail gives the widths and how many
mm of track each one has.
{img:lc_width_step}</li>
<li><b>Vias in pads</b>: the drill of a via inside an SMD pad. In reflow the
solder flows into the hole and the joint is left without it: move the via out of
the pad, or order filled and capped via-in-pad. Large pads (over 1.5 mm on both
sides, i.e. the thermal pads of QFNs) are not counted: there vias are put on
purpose.
{img:lc_via_in_pad}</li>
<li><b>Tombstoning</b>: small two-pad parts (0201 to 0805, SOD-323/523 diodes) with
one pad flooded in a zone with a solid connection and the other connected by
tracks only. In reflow the flooded pad heats up later: the other side melts first
and pulls the part up. A thermal relief on the flooded pad fixes it. The check
looks at the copper around the pad: if it surrounds it all, it is "flooded".
{img:lc_tombstone}</li>
<li><b>Via current</b>: for the nets of the <i>Currents</i> field, the vias close
to each other (within 3 mm) are a layer change carrying the whole current of the
net. <i>Measured</i> = vias present, <i>Limit</i> = vias needed for the
<i>Maximum temperature rise</i>, with the IPC-2221 formula on the via barrel
(plating from the <b>Options</b> tab, as in the DC Current tab). Error if every via
would heat more than twice the maximum.
{img:lc_via_current}</li>
<li><b>Crystal</b>: for every crystal (reference Y, or "Crystal" in the footprint
name) two checks. Tracks of other nets under the crystal, on any layer: they bring
noise into a very sensitive circuit (error). Length of the tracks between the
crystal and the IC, load capacitors included: <i>Measured</i> = length,
<i>Limit</i> = <i>Crystal-IC tracks up to</i>.
{img:lc_crystal}</li>
<li><b>Overlapping tracks</b>: tracks of two different nets one over the other
(their copper overlaps seen from above) on adjacent layers, with no plane between
them: they couple strongly (crosstalk). <i>Measured</i> = length of the
overlapping stretch, <i>Limit</i> = <i>Overlapping tracks from</i>; beyond 4 times
it is an error.
{img:lc_broadside}</li>
</ul>
<p><b>Excluding a row</b>: a warning you have reviewed and accepted (e.g. a
slow track near the edge) is excluded with a <b>right click</b> on the row,
<i>Exclude (accepted)</i>. The row turns grey and goes to the bottom of the table,
as KiCad does with the excluded DRC errors: it is not counted among errors and
warnings and it is not drawn on the board. It stays excluded in the next runs,
until you edit the objects involved (the row is recognized by them). A right click
includes it again, one or all.</p>
{img:lc_exclude}
<p><b>Data of each board</b>: the excluded rows and the <i>Net data</i> (currents,
voltages, groups) are saved in a small file next to the board,
<tt>board_name.si_toolkit.json</tt>: every board has its own. The thresholds
instead are the same for all the boards. A board never saved has no file yet: the
exclusions last while the window stays open.</p>
<p><b>Report</b>: after the checks, <i>Report...</i> writes an HTML page next to the
board (<tt>board_name_layout_checks.html</tt>) and opens it in the browser: date,
version, thresholds and data used, summary per check, drawing of the board with
the numbered problems and, for every problem, its text, measure, limit, position
and a zoomed drawing of the board there. Excluded rows are at the end, in grey.
For a PDF: from the browser <i>Print</i> -> <i>Save as PDF</i>.</p>
{img:lc_report}
<p><b>Test board</b>: in the repository, in <tt>docs/test_board</tt>, there is a
board with one case for each of the 16 checks (and its net data file). Open it and
run the checks to see how they work, or to verify the plugin after a KiCad update;
the <tt>README.md</tt> of that folder lists the expected rows.</p>
<p><b>Distances</b>: between pad and via, pin and capacitor and between two vias
they are measured copper edge to copper edge (the free space between them), not
center to center. For the stitching vias the distance goes from the ground
point to the center of the via, like the pitch of a grid.</p>
<p><b>On the board</b>, on layer <b>User.1</b> for errors and <b>User.2</b> for
warnings: a circle centred on every problem (the pin, the via, the track) and,
for the stitching vias, a filled shape covering the area too far from the vias
(it follows the grid of the check, so its edges are stepped). On the shape there
is the measure: a cross on the farthest point, a segment to the via used for the
calculation (circled) and the distance written, the same as the <i>Measured</i>
column. If the shape
covers too much, lower the opacity of the User layers in Pcbnew's Appearance
panel. Clicking a row also selects the objects involved in Pcbnew and centres
the view on them; for a stitching area the view centres on the shape and
highlights it. If the same zone is far
from the vias on several layers, it is a single row with all the layers (e.g.
F.Cu + B.Cu). <i>Clear overlay</i> removes everything; <i>Show</i> filters the
table.</p>
<p><b>Default values</b> (good-practice rules for a generic board, digital logic
up to a few hundred MHz; the <i>Defaults</i> button puts them back):</p>
<ul>
<li>capacitor within 3 mm of the pin (warning), 8 mm (error): beyond about ten mm
a 100 nF decouples little; for fast ICs 1-2 mm is better;</li>
<li>ground via within 1 mm of the GND pad: the via usually sits right next to the
pad;</li>
<li>return via within 2 mm of the signal via (error beyond 4 mm);</li>
<li>stitching vias every 10 mm, about lambda/20 at 750 MHz in FR4. RF areas need
less: with GNSS at 1.5 GHz about 5 mm;</li>
<li>plane gaps from 5 mm: shorter ones are the crossings of tracks on the other
side, unavoidable on two layers. For RF lines even 1-2 mm matter;</li>
<li>plane edge 3 h from the track: almost all the field is within 3 h. On a
1.6 mm two-layer board (h about 1.5 mm) that is about 4.5 mm, so tracks a few mm
from the board edge are reported too: for slow signals raise the threshold or
ignore them;</li>
<li>track temperature rise 10 C (error beyond 20 C);</li>
<li>pair skew 0.5 mm. Typical values: USB 2.0 about 1.25 mm, 100 Mbit Ethernet
about 1.3 mm, HDMI and PCIe 0.1-0.15 mm;</li>
<li>difference in the groups 2 mm (e.g. SD/SDIO bus); DDR needs a few tenths;</li>
<li>dead branches from 1 mm (error beyond 5 mm), acute angles below 90 degrees,
width steps above 25 %, crystal-IC tracks up to 10 mm, overlapping tracks from
5 mm.</li>
</ul>
<p><b>Limits</b> to keep in mind:</p>
<ul>
<li>The capacitor considered is the <b>nearest</b> one on the same supply,
whatever its value: a 10 uF electrolytic next to the pin passes the check even
if the 100 nF is far.</li>
<li>The layer change check covers <b>all the signals</b>, slow ones too (I2C,
buttons, LEDs) that do not need a return via: many yellow warnings can be
ignored. Supply nets are excluded with the check box.</li>
<li>The stitching via spacing is <b>one for the whole board</b>: for a more
demanding RF area run a second check with a smaller spacing and look only at
that area.</li>
<li>Only ground planes are considered: a power plane used as reference does not
count.</li>
<li>Distances are straight-line, not along the tracks.</li>
<li>The stitching areas follow a 1-2 mm grid: the edges of the shapes are
indicative, not exact.</li>
<li>Copper islands are read from the fill polygons: if this KiCad version does
not provide them, the checks go on without distinguishing the islands and say
so in the status line.</li>
<li>Track width: the <b>whole current</b> of the net is assumed on every track,
so a thin branch towards a small load is reported too. The real distribution is
in the <b>DC Current</b> tab, which also checks the vias. The IPC-2221 formula is
empirical, for isolated tracks.</li>
<li>Isolation: the IPC-2221 distances are a design minimum for the printed
board. For mains-connected equipment the safety standards (IEC 62368-1, IEC
60664) ask for larger clearance and creepage distances, depending on the kind of
insulation. Only distances on the same layer are measured.</li>
<li>Lengths: on a net with branches the length includes all of them, as in
KiCad's Net Inspector.</li>
<li>Width steps, dead branches, acute angles and overlapping tracks look at
<b>all the signal nets</b>, slow ones too, where they matter little: supply nets
are excluded with the check box. A crystal is recognized only from the Y
reference or the footprint name.</li>
</ul>

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
intensity look at the color; with <i>Moving arrows</i> they slide in the
direction of the current, faster where it is stronger. The most loaded ground vias show their share. The
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
