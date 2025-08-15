# Welcome to Rately (Name is WIP)

> THIS REQUIRES FFMPEG TO BE INSTALLED

Rately is a "simple" app that allows you to easily rate your music  
Rately supports the following formats; MP3s, WAVs, OGGs, M4As, and FLACs.  

To use Rately, all you have to do is run the `Rately.exe` (or if you are running uncompiled, `app.py`), select the folder containing your music, and click `Rate Songs`  
You can also access it without it booting a browser window, allowing you to use your own browser by running `webhost.py` and accessing it via `http://127.0.0.1:3478`
> Fair warning, ratings and comments on songs are stored via the audio files metadata, It should'nt cause problems, but bad things can always happen, so its suggested you run this on a copy of your music folder  

You can search on both the rating and rendering page, search is case insensitive, and will ignore non alphanumeric characters. You can also use `#rated` and `#rating:0-10`
> `#rating:0-10` may look like: `#rating:5-10` or `#rating:7`, it also allows decimals in the rating
> You can also invert the tag by placeing a `!` or a `-` after `#`, this may look like `#-rated` or `#!rating:0`

You can also render a card showing the song and rating if you click `Render Cards` on the home page, or `Render` at the bottom of the queue in the rating page  
> If you cancel the file chooser, the window will request a folder path from, if you cancel this aswhel, you can naviage to the homepage or render page and press `Pick Library`