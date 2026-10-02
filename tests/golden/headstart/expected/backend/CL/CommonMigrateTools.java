package hu.company.features.cl;

import java.math.BigDecimal;
import java.math.MathContext;
import java.sql.CallableStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.function.Supplier;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.CallableStatementCallback;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

/**
 * Közös segédek a migrált Oracle Forms-modulokhoz (CL).
 *
 * <p>Egyszer kell a projektbe tenni; minden generált modul ezt hívja, így egy javítás itt minden
 * modulra érvényes, újragenerálás nélkül. Java 11 és Spring Boot 2.3 (Spring Framework 5.2)
 * kompatibilis. A generált modulok a VERSION-ben megadott változatot várják: ha a migrátor új
 * változatot ad, ezt az egy fájlt kell cserélni.
 */
public final class CommonMigrateTools {
    /** A változat, amelyet a generált modulok várnak. */
    public static final String VERSION = "4";

    private CommonMigrateTools() {
        // Csak statikus segédek.
    }

    /**
     * Oracle SQL szemantika Java-értékeken: NULL = üres szöveg, háromértékű logika,
     * NUMBER-aritmetika.
     */
    public static final class SqlValues {
        private SqlValues() {
        }

        /** Üres szöveg helyett null, mint az Oracle VARCHAR2-ben. */
        public static String normalize(String value) {
            return value == null || value.isEmpty() ? null : value;
        }

        /** Igaz, ha az érték NULL (null vagy üres szöveg). */
        public static boolean isNull(Object value) {
            return value == null || "".equals(value);
        }

        /** A háromértékű logika igaz ága: a NULL hamisnak számít. */
        public static boolean truth(Boolean value) {
            return Boolean.TRUE.equals(value);
        }

        /** Oracle NOT: a NULL tagadása NULL. */
        public static Boolean not(Boolean value) {
            return value == null ? null : !value;
        }

        /** Oracle AND rövidzárral: a jobb oldal csak akkor fut, ha a bal oldal nem hamis. */
        public static Boolean and(Supplier<Boolean> left, Supplier<Boolean> right) {
            Boolean a = left.get();
            if (Boolean.FALSE.equals(a)) {
                return false;
            }
            Boolean b = right.get();
            if (Boolean.FALSE.equals(b)) {
                return false;
            }
            return a == null || b == null ? null : true;
        }

        /** Oracle OR rövidzárral: a jobb oldal csak akkor fut, ha a bal oldal nem igaz. */
        public static Boolean or(Supplier<Boolean> left, Supplier<Boolean> right) {
            Boolean a = left.get();
            if (Boolean.TRUE.equals(a)) {
                return true;
            }
            Boolean b = right.get();
            if (Boolean.TRUE.equals(b)) {
                return true;
            }
            return a == null || b == null ? null : false;
        }

        /** Oracle-összehasonlítás a megadott operátorral; NULL operandussal az eredmény NULL. */
        @SuppressWarnings({"rawtypes", "unchecked"})
        public static Boolean compare(Object left, Object right, String operator) {
            if (isNull(left) || isNull(right)) {
                return null;
            }
            int c;
            if (left instanceof BigDecimal && right instanceof BigDecimal) {
                c = ((BigDecimal) left).compareTo((BigDecimal) right);
            } else if (left.getClass() == right.getClass() && left instanceof Comparable) {
                c = ((Comparable) left).compareTo(right);
            } else {
                throw new IllegalArgumentException("Unsupported implicit Oracle conversion");
            }
            switch (operator) {
                case "=":
                    return c == 0;
                case "<>":
                case "!=":
                    return c != 0;
                case "<":
                    return c < 0;
                case ">":
                    return c > 0;
                case "<=":
                    return c <= 0;
                case ">=":
                    return c >= 0;
                default:
                    throw new IllegalArgumentException(operator);
            }
        }

        /** Egyenlőség, amelyben két NULL is egyezik (Forms-mezők összevetése). */
        public static boolean same(Object a, Object b) {
            return isNull(a) && isNull(b) || Boolean.TRUE.equals(compare(a, b, "="));
        }

        /** NUMBER-aritmetika; NULL operandussal az eredmény NULL, az osztás 38 jegyre pontos. */
        public static BigDecimal math(BigDecimal a, BigDecimal b, String operator) {
            if (a == null || b == null) {
                return null;
            }
            switch (operator) {
                case "+":
                    return a.add(b);
                case "-":
                    return a.subtract(b);
                case "*":
                    return a.multiply(b);
                case "/":
                    return a.divide(b, new MathContext(38));
                default:
                    throw new IllegalArgumentException(operator);
            }
        }

        /** Előjelváltás; a NULL NULL marad. */
        public static BigDecimal neg(BigDecimal value) {
            return value == null ? null : value.negate();
        }

        /** Abszolút érték (ABS); a NULL NULL marad. */
        public static BigDecimal abs(BigDecimal value) {
            return value == null ? null : value.abs();
        }

        /** NVL: a helyettesítő érték, ha az első érték NULL. */
        public static <T> T nvl(T value, T fallback) {
            return isNull(value) ? fallback : value;
        }

        /** Oracle-összefűzés (||): a NULL tag üres szöveg, az üres eredmény NULL. */
        public static String concat(String a, String b) {
            return normalize((a == null ? "" : a) + (b == null ? "" : b));
        }

        /** UPPER, nyelvfüggetlenül (Locale.ROOT). */
        public static String upper(String value) {
            return value == null ? null : normalize(value.toUpperCase(Locale.ROOT));
        }

        /** LOWER, nyelvfüggetlenül (Locale.ROOT). */
        public static String lower(String value) {
            return value == null ? null : normalize(value.toLowerCase(Locale.ROOT));
        }

        /** TRIM: a szóközök levágása mindkét végről. */
        public static String trim(String value) {
            return value == null ? null : normalize(value.replaceAll("^ +| +$", ""));
        }

        /** LENGTH karakterben (Unicode-kódpontban); a NULL NULL marad. */
        public static BigDecimal length(String value) {
            return isNull(value)
                    ? null
                    : BigDecimal.valueOf(value.codePointCount(0, value.length()));
        }
    }

    /** Egy Forms-trigger futásának üzenetei (MESSAGE), és a FORM_TRIGGER_FAILURE megfelelője. */
    public static final class RuleContext {
        private final List<String> messages = new ArrayList<>();

        /** MESSAGE: az üzenet a válaszba kerül (a null kimarad). */
        public void message(String value) {
            if (value != null) {
                messages.add(value);
            }
        }

        /** Az eddigi üzenetek, sorrendben. */
        public List<String> messages() {
            return List.copyOf(messages);
        }

        /** RAISE FORM_TRIGGER_FAILURE: HTTP 422 az utolsó üzenettel. */
        public void abort() {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, messages.isEmpty()
                    ? "A rekord validálása sikertelen."
                    : messages.get(messages.size() - 1));
        }
    }

    /** Hibafordító: Oracle-hibákból a Forms-viselkedésnek megfelelő HTTP-válasz, egy helyen. */
    public static final class FormsErrors {
        private static final Pattern MISSING_ROUTINE = Pattern.compile("PLS-00201[^']*'([^']+)'");

        private FormsErrors() {
        }

        /** A dobandó kivétel: üzleti hiba (422), migrációs korlát (501) vagy az eredeti. */
        public static RuntimeException translate(DataAccessException e) {
            if (e.getMostSpecificCause() instanceof SQLException) {
                SQLException ora = (SQLException) e.getMostSpecificCause();
                String text = ora.getMessage() == null ? "" : ora.getMessage();
                // ORA-20998: the migrated code changed an item it may not write back in this event.
                if (ora.getErrorCode() == 20998) {
                    return new ResponseStatusException(HttpStatus.NOT_IMPLEMENTED,
                            "Migrációs korlát: " + message(text));
                }
                // PLS-00201 (language-independent code): a routine the database does not know -
                // Forms-side code not yet in the framework catalog, or a missing database object.
                // Only this operation stops.
                Matcher missing = MISSING_ROUTINE.matcher(text);
                if (missing.find()) {
                    return new ResponseStatusException(HttpStatus.NOT_IMPLEMENTED,
                            "Nem futtatható az adatbázisban: " + missing.group(1)
                            + " nem található az adatbázisban (Forms-oldali rutin vagy hiányzó"
                            + " adatbázis-objektum); ezt a műveletet kézzel kell átültetni.");
                }
                // RAISE_APPLICATION_ERROR (ORA-20000..20999) is a business message: HTTP 422,
                // like a failed Forms trigger.
                if (ora.getErrorCode() >= 20000 && ora.getErrorCode() <= 20999) {
                    return new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                            message(text));
                }
            }
            return e;
        }

        /** Az első sor, az ORA-20xxx előtag nélkül. */
        public static String message(String text) {
            if (text == null) {
                return "Adatbázis-hiba.";
            }
            return text.lines().findFirst().orElse(text).replaceFirst("^ORA-2\\d{4}: ", "");
        }
    }

    /**
     * PL/SQL hívások: tárolt eljárás, függvény, a trigger névtelen blokkja.
     *
     * <p>A hívások a szolgáltatás tranzakciójában futnak.
     */
    public static final class DbCalls {
        private DbCalls() {
        }

        /** Egy hívási paraméter: irány (IN, OUT, IN OUT), érték és java.sql.Types típus. */
        public static final class Param {
            private final boolean in;
            private final boolean out;
            private final Object value;
            private final int type;

            /** Az irány, az érték és a java.sql.Types típus. */
            public Param(boolean in, boolean out, Object value, int type) {
                this.in = in;
                this.out = out;
                this.value = value;
                this.type = type;
            }

            /** Bemenő paraméter-e. */
            public boolean in() {
                return in;
            }

            /** Kimenő paraméter-e. */
            public boolean out() {
                return out;
            }

            /** A bemenő érték. */
            public Object value() {
                return value;
            }

            /** A java.sql.Types típus. */
            public int type() {
                return type;
            }
        }

        /** IN paraméter. */
        public static Param in(Object value, int type) {
            return new Param(true, false, value, type);
        }

        /** OUT paraméter. */
        public static Param out(int type) {
            return new Param(false, true, null, type);
        }

        /** IN OUT paraméter. */
        public static Param inOut(Object value, int type) {
            return new Param(true, true, value, type);
        }

        /**
         * Tárolt eljárás ({call PKG.PROC(?, ...)}) vagy névtelen blokk hívása.
         *
         * <p>Az OUT értékek a 0-tól számozott paraméterpozíción vannak.
         */
        public static Object[] call(NamedParameterJdbcTemplate jdbc, String sql, Param... params) {
            return run(jdbc, sql, params);
        }

        /** Tárolt függvény ({? = call PKG.FUNC(?, ...)}) hívása: a függvény eredménye. */
        public static Object function(NamedParameterJdbcTemplate jdbc, String sql, int type,
                Param... params) {
            Param[] all = new Param[params.length + 1];
            all[0] = out(type);
            System.arraycopy(params, 0, all, 1, params.length);
            return run(jdbc, sql, all)[0];
        }

        private static Object[] run(NamedParameterJdbcTemplate jdbc, String sql, Param[] params) {
            try {
                CallableStatementCallback<Object[]> callback = cs -> {
                    for (int i = 0; i < params.length; i++) {
                        Param p = params[i];
                        if (p.in()) {
                            if (p.value() == null) {
                                cs.setNull(i + 1, p.type());
                            } else {
                                cs.setObject(i + 1, p.value(), p.type());
                            }
                        }
                        if (p.out()) {
                            cs.registerOutParameter(i + 1, p.type());
                        }
                    }
                    cs.execute();
                    Object[] result = new Object[params.length];
                    for (int i = 0; i < params.length; i++) {
                        if (params[i].out()) {
                            result[i] = read(cs, i + 1, params[i].type());
                        }
                    }
                    return result;
                };
                return jdbc.getJdbcTemplate().execute(sql, callback);
            } catch (DataAccessException e) {
                throw FormsErrors.translate(e);
            }
        }

        private static Object read(CallableStatement cs, int index, int type) throws SQLException {
            if (type == Types.NUMERIC) {
                return cs.getBigDecimal(index);
            }
            if (type == Types.TIMESTAMP) {
                return cs.getObject(index, LocalDateTime.class);
            }
            return SqlValues.normalize(cs.getString(index));
        }
    }

    /** Gombkérés értékei (Oracle-nevek, szövegként) és a PL/SQL-kötések típusos értékei között. */
    public static final class PlsqlValues {
        private PlsqlValues() {
        }

        /** A BLOKK.MEZŐ szöveges értéke; az üres szöveg NULL. */
        public static String text(Map<String, Map<String, String>> blocks, String block,
                String item) {
            Map<String, String> values = blocks.get(block);
            String value = values == null ? null : values.get(item);
            return value == null || value.isEmpty() ? null : value;
        }

        /** A BLOKK.MEZŐ értéke számként; hibás számra HTTP 422. */
        public static BigDecimal number(Map<String, Map<String, String>> blocks, String block,
                String item) {
            String value = text(blocks, block, item);
            try {
                return value == null ? null : new BigDecimal(value.trim());
            } catch (NumberFormatException e) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        block + "." + item + ": hibás szám.", e);
            }
        }

        /** A BLOKK.MEZŐ értéke dátumként (ISO); hibás dátumra HTTP 422. */
        public static LocalDateTime datetime(Map<String, Map<String, String>> blocks, String block,
                String item) {
            String value = text(blocks, block, item);
            try {
                if (value == null) {
                    return null;
                }
                String trimmed = value.trim();
                return trimmed.length() == 10
                        ? LocalDate.parse(trimmed).atStartOfDay()
                        : LocalDateTime.parse(trimmed);
            } catch (DateTimeParseException e) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        block + "." + item + ": hibás dátum (ISO: éééé-hh-nnTóó:pp:mm).", e);
            }
        }

        /** Egy Forms-paraméter értéke; az üres szöveg NULL. */
        public static String parameter(Map<String, String> parameters, String name) {
            String value = parameters.get(name);
            return value == null || value.isEmpty() ? null : value;
        }

        /** Egy BLOKK.MEZŐ értékének visszaírása szövegként (a szám tizedes alakban). */
        public static void put(Map<String, Map<String, String>> blocks, String block, String item,
                Object value) {
            blocks.computeIfAbsent(block, key -> new LinkedHashMap<>())
                    .put(item, value == null ? null
                            : value instanceof BigDecimal ? ((BigDecimal) value).toPlainString()
                            : value.toString());
        }

        /** A PL/SQL üzenetpuffer nem üres sorai. */
        public static List<String> lines(Object messages) {
            if (!(messages instanceof String)) {
                return List.of();
            }
            return Arrays.stream(((String) messages).split("\n"))
                    .filter(line -> !line.isBlank())
                    .collect(Collectors.toList());
        }

        /**
         * A Forms-emuláció felületi utasításai (GO_BLOCK, SET_ITEM_PROPERTY, SHOW_ALERT ...).
         *
         * <p>Egy utasítás: [művelet, argumentumok...]; a puffert a PL/SQL niva_cmd tölti
         * (CHR(30) az utasítások, CHR(31) a mezők között). A záró üres argumentumok elmaradnak.
         */
        public static List<List<String>> commands(Object buffer) {
            if (!(buffer instanceof String)) {
                return List.of();
            }
            List<List<String>> result = new ArrayList<>();
            for (String command : ((String) buffer).split(String.valueOf((char) 30))) {
                if (command.isEmpty()) {
                    continue;
                }
                String[] parts = command.split(String.valueOf((char) 31), -1);
                List<String> fields = new ArrayList<>(Arrays.asList(parts));
                while (fields.size() > 1 && fields.get(fields.size() - 1).isEmpty()) {
                    fields.remove(fields.size() - 1);
                }
                result.add(fields);
            }
            return result;
        }

        /**
         * COMMIT_FORM egy gomb kódjának közepén (mentési pont): a mentés előtti kódrész ellenőrzése.
         *
         * <p>A commitForm a gomb kódját a mentési pontig újrafuttatja; ugyanoda és ugyanazokkal a
         * mezőértékekkel kell érkeznie, mint a képernyő előző kérése (NIVA.COMMIT_POINT,
         * NIVA.COMMIT_STATE). Eltérésre HTTP 409, a tranzakció visszagörgetve. Az eredmény a gomb
         * felületi utasításai a NIVA_COMMIT jelölő nélkül.
         */
        public static List<List<String>> prelude(List<List<String>> commands, Map<String, String> parameters) {
            String point = parameter(parameters, "NIVA.COMMIT_POINT");
            String state = parameter(parameters, "NIVA.COMMIT_STATE");
            boolean reached = false;
            List<List<String>> result = new ArrayList<>();
            for (List<String> command : commands) {
                if (!command.isEmpty() && "NIVA_COMMIT".equals(command.get(0))) {
                    String at = command.size() > 1 ? command.get(1) : "";
                    String now = command.size() > 2 && !command.get(2).isEmpty() ? command.get(2) : null;
                    reached = point != null && point.equals(at) && (state == null ? now == null : state.equals(now));
                    continue;
                }
                result.add(command);
            }
            if (!reached) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "A mentés előtti kód nem ugyanott vagy nem "
                        + "ugyanazokkal az értékekkel állt meg, mint az előző kérésben. Frissítsd az adatokat, és "
                        + "próbáld újra.");
            }
            return result;
        }

        /** Egy :GLOBAL érték visszaadása a képernyőnek (a NULL is: a változó törölhető). */
        public static void global(Map<String, String> globals, String name, Object value) {
            globals.put(name, value == null ? null
                    : value instanceof BigDecimal ? ((BigDecimal) value).toPlainString()
                    : value.toString());
        }
    }

    /**
     * LOV (rekordcsoport) lekérdezése.
     *
     * <p>A beírt szöveggel szűrve, a Forms-kötésekkel, korlátozott sorszámmal.
     */
    public static final class LovQuery {
        /** Az alapértelmezett sorszám. */
        public static final int DEFAULT_LIMIT = 50;

        /** A legnagyobb kérhető sorszám. */
        public static final int MAX_LIMIT = 500;

        private LovQuery() {
        }

        /**
         * A LOV sorai: az Oracle NUMBER tizedes szövegként, a dátum ISO-szövegként.
         *
         * @param jdbc       a szolgáltatás JDBC-sablonja
         * @param sql        a LOV lekérdezése
         * @param term       a beírt szöveg (LIKE 'term%' a megjelenített oszlopon), ha szűrhető
         * @param parameters a Forms-kötések értékei BLOKK.MEZŐ szerint
         * @param limit      a kért sorszám (alapértelmezés: DEFAULT_LIMIT)
         * @param binds      {SQL-kötés neve, BLOKK.MEZŐ, típus} hármasok
         * @param filtered   szűrhető-e a LOV a beírt szöveggel
         * @return a sorok, oszlopnév szerint
         */
        public static List<Map<String, Object>> rows(NamedParameterJdbcTemplate jdbc, String sql,
                String term, Map<String, String> parameters, Integer limit, String[][] binds,
                boolean filtered) {
            int rows = limit == null ? DEFAULT_LIMIT : limit;
            if (rows < 1 || rows > MAX_LIMIT) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        "limit: 1.." + MAX_LIMIT + " szükséges.");
            }
            MapSqlParameterSource params = new MapSqlParameterSource().addValue("limit", rows);
            if (filtered) {
                params.addValue("term", term == null || term.isEmpty() ? null : term);
            }
            Map<String, String> given = parameters == null ? Map.of() : parameters;
            for (String[] bind : binds) {
                params.addValue(bind[0], value(given.get(bind[1]), bind[1], bind[2]));
            }
            List<Map<String, Object>> result = new ArrayList<>();
            for (Map<String, Object> row : jdbc.queryForList(sql, params)) {
                Map<String, Object> copy = new LinkedHashMap<>();
                // Oracle NUMBER stays a decimal string on the wire, dates are ISO text.
                row.forEach((k, v) -> copy.put(k, v instanceof BigDecimal
                        ? ((BigDecimal) v).toPlainString()
                        : v instanceof Timestamp
                        ? ((Timestamp) v).toLocalDateTime().toString()
                        : v));
                result.add(copy);
            }
            return result;
        }

        private static Object value(String raw, String source, String type) {
            if (raw == null || raw.isEmpty()) {
                return null;
            }
            try {
                if ("number".equals(type)) {
                    return new BigDecimal(raw.trim());
                }
                if ("datetime".equals(type)) {
                    return LocalDateTime.parse(raw.trim());
                }
                return raw;
            } catch (RuntimeException e) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        source + ": hibás " + type + " érték.", e);
            }
        }
    }

    /**
     * A Forms-mezőszabályok (Required, MaximumLength, NUMBER pontosság) ellenőrzése.
     *
     * <p>Külön validációs könyvtár nélkül.
     */
    public static final class FormsChecks {
        private FormsChecks() {
        }

        /** Required: az üres érték hiba. */
        public static void required(List<String> errors, String field, Object value) {
            if (value == null || "".equals(value)) {
                errors.add(field + ": kötelező");
            }
        }

        /** MaximumLength: legfeljebb max karakter (Unicode-kódpont). */
        public static void maxLength(List<String> errors, String field, String value, int max) {
            if (value != null && value.codePointCount(0, value.length()) > max) {
                errors.add(field + ": legfeljebb " + max + " karakter");
            }
        }

        /** NUMBER(p, s): legfeljebb integer egész és fraction tizedes jegy. */
        public static void digits(List<String> errors, String field, BigDecimal value, int integer,
                int fraction) {
            if (value == null) {
                return;
            }
            BigDecimal v = value.stripTrailingZeros();
            int scale = Math.max(v.scale(), 0);
            int whole = Math.max(v.precision() - v.scale(), 0);
            if (scale > fraction || whole > integer) {
                errors.add(field + ": legfeljebb " + integer + " egész és " + fraction
                        + " tizedes jegy");
            }
        }

        /** HTTP 422 az összes hibával, ha van. */
        public static void throwIfAny(List<String> errors) {
            if (!errors.isEmpty()) {
                throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                        String.join("; ", errors.stream().sorted().collect(Collectors.toList())));
            }
        }
    }
}
