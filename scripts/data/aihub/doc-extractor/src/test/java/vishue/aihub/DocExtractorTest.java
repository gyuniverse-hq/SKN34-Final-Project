package vishue.aihub;

import org.junit.jupiter.api.Test;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import java.io.ByteArrayOutputStream;
import static org.junit.jupiter.api.Assertions.*;

class DocExtractorTest {
    @Test void paragraphsCellsAndUtf16Roundtrip() throws Exception {
        byte[] bytes;
        try (var doc = new XWPFDocument(); var out = new ByteArrayOutputStream()) {
            var run = doc.createParagraph().createRun();
            run.setText("한글😀"); run.addTab(); run.setText("탭"); run.addBreak(); run.setText("다음");
            doc.createParagraph();
            var table = doc.createTable(1, 2);
            table.getRow(0).getCell(0).setText("왼쪽");
            table.getRow(0).getCell(1).setText("오른쪽");
            doc.createParagraph().createRun().setText("표 뒤");
            doc.write(out); bytes = out.toByteArray();
        }
        var r = DocExtractor.extract("misleading.doc", bytes);
        assertEquals("success", r.status(), r.error_code()); assertTrue(r.verified());
        assertEquals(5, r.blocks().size());
        assertEquals("한글😀\t탭\n다음", r.blocks().get(0).text_raw());
        assertEquals(2, r.blocks().stream().filter(b -> b.block_type().equals("table_cell")).count());
        assertEquals("표 뒤", r.blocks().get(4).text_raw());
        assertEquals(r.blocks().get(0).text_raw().length(), r.blocks().get(0).source_locator().end());
        assertEquals(r, DocExtractor.extract("misleading.doc", bytes));
    }
    @Test void badAndUnsupportedInputs() throws Exception {
        assertEquals("empty_file", DocExtractor.extract("empty.doc", new byte[0]).error_code());
        assertEquals("unsupported", DocExtractor.extract("rtf.doc", "{\\rtf1 test}".getBytes()).status());
        assertEquals("failed", DocExtractor.extract("bad.doc", new byte[]{80,75,3,4}).status());
        assertEquals("failed", DocExtractor.extract("ole.doc", DocExtractor.OLE).status());
    }
}
