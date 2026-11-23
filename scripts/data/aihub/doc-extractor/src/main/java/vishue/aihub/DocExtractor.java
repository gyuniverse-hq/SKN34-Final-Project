package vishue.aihub;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.poi.hwpf.HWPFDocument;
import org.apache.poi.hwpf.usermodel.*;
import org.apache.poi.openxml4j.util.ZipInputStreamZipEntrySource;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.w3c.dom.Node;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.ZipFile;

/** Main body only. stdout is aggregate JSON unless --emit-records is explicit. */
public final class DocExtractor {
    static { System.setProperty("log4j2.statusLoggerLevel", "OFF"); }
    static final ObjectMapper JSON = new ObjectMapper();
    static final String VERSION = "body-v1";
    static final String W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
    static final byte[] OLE = HexFormat.of().parseHex("d0cf11e0a1b11ae1");
    static final int MAX_DOCUMENT_BYTES = 128 * 1024 * 1024;
    public record Locator(String format, String unit, String part, List<Integer> path,
                          int paragraph, int table, int row, int cell, int start, int end) {}
    public record Block(int block_order, String block_type, String text_raw,
                        String text_sha256, Locator source_locator) {}
    public record Result(String source_path, String source_sha256, String detected_format,
                         String parser_version, String extraction_version, String status,
                         String error_code, List<String> warnings, boolean verified,
                         List<Block> blocks) {}

    static String sha(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    static String format(byte[] bytes) {
        if (bytes.length == 0) return "empty";
        if (bytes.length >= 8 && Arrays.equals(Arrays.copyOf(bytes, 8), OLE)) return "ole";
        if (bytes.length >= 4 && bytes[0] == 'P' && bytes[1] == 'K') return "ooxml";
        if (new String(bytes, 0, Math.min(32, bytes.length), StandardCharsets.US_ASCII)
                .stripLeading().startsWith("{\\rtf")) return "rtf";
        return "unknown";
    }
    static void add(List<Block> blocks, String kind, String text, Locator loc) throws Exception {
        blocks.add(new Block(blocks.size(), kind, text, sha(text.getBytes(StandardCharsets.UTF_8)), loc));
    }
    static List<Table> tables(Range range) {
        var result = new ArrayList<Table>();
        var iterator = new TableIterator(range);
        while (iterator.hasNext()) result.add(iterator.next());
        return result;
    }
    static List<Block> ole(HWPFDocument doc) throws Exception {
        Range body = doc.getRange();
        var blocks = new ArrayList<Block>();
        var tables = tables(body);
        for (int t = 0; t < tables.size(); t++) {
            Table table = tables.get(t);
            for (int r = 0; r < table.numRows(); r++) {
                TableRow row = table.getRow(r);
                for (int c = 0; c < row.numCells(); c++) {
                    TableCell cell = row.getCell(c);
                    add(blocks, "table_cell", cell.text(), new Locator("ole", "utf16", "main", List.of(),
                            -1, t, r, c, cell.getStartOffset(), cell.getEndOffset()));
                }
            }
        }
        for (int i = 0; i < body.numParagraphs(); i++) {
            Paragraph p = body.getParagraph(i);
            boolean covered = blocks.stream().anyMatch(b -> b.source_locator.start <= p.getStartOffset()
                    && b.source_locator.end >= p.getEndOffset());
            if (!covered) add(blocks, "paragraph", p.text(), new Locator("ole", "utf16", "main", List.of(),
                    i, -1, -1, -1, p.getStartOffset(), p.getEndOffset()));
        }
        blocks.sort(Comparator.comparingInt(b -> b.source_locator.start));
        var ordered = new ArrayList<Block>();
        for (Block b : blocks) ordered.add(new Block(ordered.size(), b.block_type, b.text_raw,
                b.text_sha256, b.source_locator));
        return ordered;
    }
    static boolean word(Node n, String name) {
        return W.equals(n.getNamespaceURI()) && name.equals(n.getLocalName());
    }
    static List<Node> children(Node n) {
        var result = new ArrayList<Node>();
        for (Node c = n.getFirstChild(); c != null; c = c.getNextSibling())
            if (c.getNodeType() == Node.ELEMENT_NODE) result.add(c);
        return result;
    }
    static String xmlText(Node n) {
        // Textboxes/drawings, field instructions and deleted revisions are outside body-v1.
        if (word(n, "txbxContent") || word(n, "drawing") || word(n, "del")) return "";
        if (word(n, "t")) {
            var text = new StringBuilder();
            for (Node c = n.getFirstChild(); c != null; c = c.getNextSibling())
                if (c.getNodeType() == Node.TEXT_NODE || c.getNodeType() == Node.CDATA_SECTION_NODE)
                    text.append(c.getNodeValue());
            return text.toString();
        }
        if (word(n, "tab")) return "\t";
        if (word(n, "br") || word(n, "cr")) return "\n";
        var out = new StringBuilder();
        for (Node c : children(n)) {
            out.append(xmlText(c));
            if (word(c, "p")) out.append('\n');
        }
        return out.toString();
    }
    static void walk(Node n, List<Integer> path, List<Block> blocks) throws Exception {
        if (word(n, "p") || word(n, "tc")) {
            String text = xmlText(n);
            add(blocks, word(n, "tc") ? "table_cell" : "paragraph", text,
                    new Locator("ooxml", "utf16", "/word/document.xml", List.copyOf(path),
                            -1, -1, -1, -1, 0, text.length()));
            return; // Cell text is emitted once, including its nested paragraphs/tables.
        }
        var elements = children(n);
        for (int i = 0; i < elements.size(); i++) {
            path.add(i); walk(elements.get(i), path, blocks); path.remove(path.size() - 1);
        }
    }
    static Node body(XWPFDocument doc) { return doc.getDocument().getBody().getDomNode(); }
    static String locate(HWPFDocument doc, Locator l) {
        Range r = l.paragraph >= 0 ? doc.getRange().getParagraph(l.paragraph)
                : tables(doc.getRange()).get(l.table).getRow(l.row).getCell(l.cell);
        if (r.getStartOffset() != l.start || r.getEndOffset() != l.end)
            throw new IllegalStateException("locator_range_mismatch");
        return r.text();
    }
    static String locate(XWPFDocument doc, Locator l) {
        Node n = body(doc);
        for (int i : l.path) n = children(n).get(i);
        if (!word(n, "p") && !word(n, "tc")) throw new IllegalStateException("locator_type_mismatch");
        return xmlText(n);
    }
    static Result extract(String path, byte[] bytes) throws Exception {
        String digest = sha(bytes), kind = format(bytes);
        var blocks = new ArrayList<Block>();
        var warnings = new ArrayList<String>();
        String status = "success", error = null;
        boolean verified = false;
        try {
            if (kind.equals("ole")) {
                try (var doc = new HWPFDocument(new ByteArrayInputStream(bytes))) { blocks.addAll(ole(doc)); }
                try (var fresh = new HWPFDocument(new ByteArrayInputStream(bytes))) {
                    for (Block b : blocks) if (!b.text_raw.equals(locate(fresh, b.source_locator)))
                        throw new IllegalStateException("roundtrip_mismatch");
                }
                verified = true;
            } else if (kind.equals("ooxml")) {
                try (var doc = new XWPFDocument(new ByteArrayInputStream(bytes))) {
                    walk(body(doc), new ArrayList<>(), blocks);
                }
                try (var fresh = new XWPFDocument(new ByteArrayInputStream(bytes))) {
                    for (Block b : blocks) if (!b.text_raw.equals(locate(fresh, b.source_locator)))
                        throw new IllegalStateException("roundtrip_mismatch");
                }
                verified = true;
            } else {
                status = kind.equals("empty") ? "failed" : "unsupported";
                error = kind.equals("empty") ? "empty_file" : "unsupported_format";
            }
            if (blocks.stream().anyMatch(b -> b.text_raw.indexOf('\ufffd') >= 0))
                warnings.add("replacement_character");
        } catch (Exception e) {
            status = "failed"; error = e.getClass().getSimpleName(); blocks.clear();
        }
        return new Result(path, digest, kind, "apache-poi-5.5.1", VERSION, status, error,
                warnings, verified, blocks);
    }
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || args.length > 2 || (args.length == 2 && !args[1].equals("--emit-records")))
            throw new IllegalArgumentException("Usage: java -jar doc-extractor.jar Other.zip [--emit-records]");
        ZipInputStreamZipEntrySource.setThresholdBytesForTempFiles(-1);
        boolean emit = args.length == 2;
        var counts = new TreeMap<String, Long>();
        var seen = new HashSet<String>();
        try (var zip = new ZipFile(Path.of(args[0]).toFile());
             var out = new PrintWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8))) {
            var entries = zip.entries();
            while (entries.hasMoreElements()) {
                var entry = entries.nextElement();
                if (entry.isDirectory() || !entry.getName().toLowerCase(Locale.ROOT).endsWith(".doc")) continue;
                counts.merge("physical_documents", 1L, Long::sum);
                byte[] bytes;
                try (var stream = zip.getInputStream(entry)) { bytes = stream.readNBytes(MAX_DOCUMENT_BYTES + 1); }
                if (bytes.length > MAX_DOCUMENT_BYTES) throw new IOException("document_size_limit");
                if (!seen.add(sha(bytes))) continue;
                Result result = extract(entry.getName(), bytes);
                counts.merge(result.detected_format + "." + result.status, 1L, Long::sum);
                for (Block b : result.blocks) counts.merge(result.detected_format + "." + b.block_type, 1L, Long::sum);
                if (result.verified) counts.merge("verified_documents", 1L, Long::sum);
                if (!result.warnings.isEmpty()) counts.merge("warning_documents", 1L, Long::sum);
                if (emit) out.println(JSON.writeValueAsString(result));
                if (seen.size() % 100 == 0) System.err.println("Processed unique documents: " + seen.size());
            }
            counts.put("unique_documents", (long) seen.size());
            if (!emit) out.println(JSON.writeValueAsString(counts));
            else System.err.println(JSON.writeValueAsString(counts));
        }
    }
}
