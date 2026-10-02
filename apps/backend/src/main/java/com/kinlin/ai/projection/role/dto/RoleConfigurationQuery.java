package com.kinlin.ai.projection.role.dto;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.core.type.WritableTypeId;
import com.fasterxml.jackson.databind.JsonSerializable;
import com.fasterxml.jackson.databind.SerializerProvider;
import com.fasterxml.jackson.databind.jsontype.TypeSerializer;

import java.io.IOException;
import java.math.BigDecimal;
import java.util.List;
import java.util.Objects;

/**
 * Isolated, immutable representation of the three user-editable role configuration objects.
 * Only explicit JSON value kinds are allowed; no persistence objects or arbitrary Java values
 * are retained. Serialization preserves the existing editor round-trip shape, including
 * custom keys. This representation is not a general extension field for identity DTOs.
 */
public record RoleConfigurationQuery(List<Property> properties) implements JsonSerializable {
    public RoleConfigurationQuery { properties = List.copyOf(properties); }

    public record Property(String name, Value value) {
        public Property {
            Objects.requireNonNull(name);
            Objects.requireNonNull(value);
        }
    }

    public sealed interface Value permits TextValue, NumericValue, BooleanValue, NullValue,
            ArrayValue, PropertiesValue { }
    public record TextValue(String value) implements Value {
        public TextValue { Objects.requireNonNull(value); }
    }
    public record NumericValue(BigDecimal value) implements Value {
        public NumericValue { Objects.requireNonNull(value); }
    }
    public record BooleanValue(boolean value) implements Value { }
    public record NullValue() implements Value { }
    public record ArrayValue(List<Value> values) implements Value {
        public ArrayValue { values = List.copyOf(values); }
    }
    public record PropertiesValue(List<Property> properties) implements Value {
        public PropertiesValue { properties = List.copyOf(properties); }
    }

    @Override
    public void serialize(JsonGenerator generator, SerializerProvider provider) throws IOException {
        generator.writeStartObject();
        writeProperties(generator, properties);
        generator.writeEndObject();
    }

    @Override
    public void serializeWithType(JsonGenerator generator, SerializerProvider provider,
                                  TypeSerializer typeSerializer) throws IOException {
        WritableTypeId id = typeSerializer.writeTypePrefix(generator,
                typeSerializer.typeId(this, JsonToken.START_OBJECT));
        writeProperties(generator, properties);
        typeSerializer.writeTypeSuffix(generator, id);
    }

    private static void writeProperties(JsonGenerator generator, List<Property> properties) throws IOException {
        for (Property property : properties) {
            generator.writeFieldName(property.name());
            writeValue(generator, property.value());
        }
    }

    private static void writeValue(JsonGenerator generator, Value value) throws IOException {
        if (value instanceof TextValue text) {
            generator.writeString(text.value());
        } else if (value instanceof NumericValue number) {
            generator.writeNumber(number.value());
        } else if (value instanceof BooleanValue bool) {
            generator.writeBoolean(bool.value());
        } else if (value instanceof NullValue) {
            generator.writeNull();
        } else if (value instanceof ArrayValue array) {
            generator.writeStartArray();
            for (Value item : array.values()) { writeValue(generator, item); }
            generator.writeEndArray();
        } else if (value instanceof PropertiesValue object) {
            generator.writeStartObject();
            writeProperties(generator, object.properties());
            generator.writeEndObject();
        }
    }
}
