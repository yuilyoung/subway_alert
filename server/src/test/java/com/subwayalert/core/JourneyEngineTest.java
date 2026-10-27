package com.subwayalert.core;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertTrue;
class JourneyEngineTest {
    @Test void deterministicRules() { assertTrue(JourneyEngineChecks.run() >= 25); }
}
