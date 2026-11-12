/*
    filetype_triage.yar - bundled rules for yarasort

    Identifies what a file IS by its content (magic bytes and internal
    structure), never by its extension.

    Layout:
      * private rules  fmt_*   one per format, never reported
      * public rules   *_Files one per category; yarasort maps these to folders

    These are triage rules, not malware signatures: they say what kind of file
    something is, not whether it is safe.
*/

/* ===================== executables ===================== */

private rule fmt_pe
{
    condition:
        filesize > 64 and
        uint16(0) == 0x5A4D and
        uint32(uint32(0x3C)) == 0x00004550
}

private rule fmt_elf
{
    condition:
        filesize > 16 and uint32(0) == 0x464C457F
}

/* ===================== packages ===================== */

private rule fmt_apk
{
    strings:
        $man = "AndroidManifest.xml"
        $dex = "classes.dex"
    condition:
        uint32(0) == 0x04034B50 and all of them
}

private rule fmt_jar
{
    strings:
        $mf  = "META-INF/MANIFEST.MF"
        $cls = ".class"
        $apk = "AndroidManifest.xml"
    condition:
        uint32(0) == 0x04034B50 and any of ($mf, $cls) and not $apk
}

private rule fmt_deb
{
    strings:
        $sig = "!<arch>\x0Adebian-binary"
    condition:
        $sig at 0
}

private rule fmt_rpm
{
    strings:
        $sig = { ED AB EE DB }
    condition:
        $sig at 0
}

private rule fmt_flatpakref
{
    strings:
        $hdr = "[Flatpak Ref]"
    condition:
        $hdr at 0
}

/* ===================== documents ===================== */

private rule fmt_pdf
{
    strings:
        $hdr = "%PDF-"
    condition:
        $hdr at 0
}

private rule fmt_ooxml
{
    strings:
        $ct = "[Content_Types].xml"
        $w  = "word/document.xml"
        $x  = "xl/workbook.xml"
        $p  = "ppt/presentation.xml"
    condition:
        uint32(0) == 0x04034B50 and $ct and any of ($w, $x, $p)
}

private rule fmt_odf_epub
{
    strings:
        $odf  = "mimetypeapplication/vnd.oasis.opendocument."
        $epub = "mimetypeapplication/epub+zip"
    condition:
        uint32(0) == 0x04034B50 and ($odf at 30 or $epub at 30)
}

private rule fmt_rtf
{
    strings:
        $sig = "{\\rtf"
    condition:
        $sig at 0
}

private rule fmt_ole2
{
    strings:
        $sig = { D0 CF 11 E0 A1 B1 1A E1 }
    condition:
        $sig at 0
}

/* ===================== images ===================== */

private rule fmt_png
{
    condition:
        uint32(0) == 0x474E5089 and uint32(4) == 0x0A1A0A0D
}

private rule fmt_jpeg
{
    condition:
        uint16(0) == 0xD8FF and uint8(2) == 0xFF
}

private rule fmt_gif
{
    strings:
        $a = "GIF87a"
        $b = "GIF89a"
    condition:
        $a at 0 or $b at 0
}

private rule fmt_bmp
{
    condition:
        filesize > 26 and uint16(0) == 0x4D42 and
        (
            uint32(14) == 12  or uint32(14) == 40  or uint32(14) == 52 or
            uint32(14) == 56  or uint32(14) == 108 or uint32(14) == 124
        )
}

private rule fmt_tiff
{
    condition:
        uint32(0) == 0x002A4949 or uint32(0) == 0x2A004D4D
}

private rule fmt_webp
{
    strings:
        $riff = "RIFF"
        $webp = "WEBP"
    condition:
        $riff at 0 and $webp at 8
}

private rule fmt_svg
{
    strings:
        $decl = "<?xml"
        $svg  = "<svg" nocase
    condition:
        $svg in (0..64) or ($decl at 0 and $svg in (0..512))
}

/* ===================== audio ===================== */

private rule fmt_mp3
{
    strings:
        $id3 = "ID3"
    condition:
        filesize > 128 and
        ($id3 at 0 or uint16be(0) == 0xFFFB or uint16be(0) == 0xFFF3 or uint16be(0) == 0xFFF2)
}

private rule fmt_flac
{
    strings:
        $sig = "fLaC"
    condition:
        $sig at 0
}

private rule fmt_ogg
{
    strings:
        $sig = "OggS"
    condition:
        $sig at 0
}

private rule fmt_wav
{
    strings:
        $riff = "RIFF"
        $wave = "WAVE"
    condition:
        $riff at 0 and $wave at 8
}

private rule fmt_m4a
{
    strings:
        $ftyp = "ftyp"
        $m4a  = "M4A "
        $m4b  = "M4B "
    condition:
        $ftyp at 4 and ($m4a at 8 or $m4b at 8)
}

/* ===================== video ===================== */

private rule fmt_mp4_mov
{
    strings:
        $ftyp = "ftyp"
        $m4a  = "M4A "
        $m4b  = "M4B "
    condition:
        $ftyp at 4 and not ($m4a at 8 or $m4b at 8)
}

private rule fmt_matroska
{
    strings:
        $sig = { 1A 45 DF A3 }
    condition:
        $sig at 0
}

private rule fmt_avi
{
    strings:
        $riff = "RIFF"
        $avi  = "AVI "
    condition:
        $riff at 0 and $avi at 8
}

/* ===================== data ===================== */

private rule fmt_sqlite
{
    strings:
        $sig = "SQLite format 3"
    condition:
        $sig at 0
}

/* ===================== web / markup ===================== */

private rule fmt_xml
{
    strings:
        $decl = "<?xml"
        $bom  = { EF BB BF 3C 3F 78 6D 6C }
    condition:
        $decl at 0 or $bom at 0
}

private rule fmt_html
{
    strings:
        $doctype = "<!doctype html" nocase
        $html    = "<html" nocase
    condition:
        $doctype in (0..256) or $html in (0..1024)
}

/* ===================== scripts ===================== */

private rule fmt_shebang
{
    strings:
        $sb = "#!"
    condition:
        $sb at 0
}

private rule fmt_python
{
    strings:
        $import = "import "
        $def    = "def "
        $main   = "if __name__"
    condition:
        filesize < 5MB and $import and ($def or $main)
}

/* ===================== archives ===================== */

private rule fmt_zip
{
    condition:
        uint32(0) == 0x04034B50
}

private rule fmt_rar5
{
    strings:
        $sig = { 52 61 72 21 1A 07 01 00 }
    condition:
        $sig at 0
}

private rule fmt_tar
{
    strings:
        $ustar = "ustar"
    condition:
        filesize > 512 and $ustar at 257
}

private rule fmt_7z
{
    strings:
        $sig = { 37 7A BC AF 27 1C }
    condition:
        $sig at 0
}

private rule fmt_gzip
{
    condition:
        filesize > 18 and uint16(0) == 0x8B1F and uint8(2) == 0x08
}

private rule fmt_bzip2
{
    strings:
        $sig = "BZh"
    condition:
        $sig at 0 and uint8(3) >= 0x31 and uint8(3) <= 0x39
}

private rule fmt_xz
{
    strings:
        $sig = { FD 37 7A 58 5A 00 }
    condition:
        $sig at 0
}

private rule fmt_zstd
{
    strings:
        $sig = { 28 B5 2F FD }
    condition:
        $sig at 0
}

private rule fmt_iso
{
    strings:
        $cd = "CD001"
    condition:
        $cd at 32769
}

/* ================================================================
   Category rules. These names are what yarasort's config maps to
   folders. Add your own rules in a separate file (see README).
   ================================================================ */

rule Executable_Files
{
    meta:
        formats = "Windows PE (exe, dll), Linux ELF (binaries, .so, AppImage)"
    condition:
        fmt_pe or fmt_elf
}

rule Package_Files
{
    meta:
        formats = "Android APK, Java JAR, Debian .deb, RPM, Flatpak ref"
    condition:
        fmt_apk or fmt_jar or fmt_deb or fmt_rpm or fmt_flatpakref
}

rule Document_Files
{
    meta:
        formats = "PDF, docx/xlsx/pptx, OpenDocument, EPUB, RTF, legacy Office (OLE2, also matches .msi)"
    condition:
        fmt_pdf or fmt_ooxml or fmt_odf_epub or fmt_rtf or fmt_ole2
}

rule Image_Files
{
    meta:
        formats = "PNG, JPEG, GIF, BMP, TIFF, WebP, SVG"
    condition:
        fmt_png or fmt_jpeg or fmt_gif or fmt_bmp or fmt_tiff or fmt_webp or fmt_svg
}

rule Audio_Files
{
    meta:
        formats = "MP3, FLAC, OGG, WAV, M4A"
    condition:
        fmt_mp3 or fmt_flac or fmt_ogg or fmt_wav or fmt_m4a
}

rule Video_Files
{
    meta:
        formats = "MP4/MOV, MKV/WebM, AVI"
    condition:
        fmt_mp4_mov or fmt_matroska or fmt_avi
}

rule Data_Files
{
    meta:
        formats = "SQLite databases"
    condition:
        fmt_sqlite
}

rule Web_And_Markup_Files
{
    meta:
        formats = "HTML, XML"
    condition:
        fmt_xml or fmt_html
}

rule Script_Files
{
    meta:
        formats = "Anything starting with a #! line, Python (heuristic)"
    condition:
        fmt_shebang or fmt_python
}

rule Archive_Files
{
    meta:
        formats = "ZIP, RAR5, TAR, 7z, gzip, bzip2, xz, zstd, ISO"
    condition:
        fmt_zip or fmt_rar5 or fmt_tar or fmt_7z or fmt_gzip or fmt_bzip2 or fmt_xz or fmt_zstd or fmt_iso
}
