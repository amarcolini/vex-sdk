import re
import glob
import sys
import os

filenames = glob.glob(sys.argv[1] + "/*.rs")
# functions = re.findall(r"pub\s+fn\s+(?:vexDevice)?(\w+)\s*\(([^\(\)]+)\)(?:\s+->\s+(.+)(?:,|$))?", function_block.group(1))

java_type_map = {
    "u32" : "int",
    "i32" : "int",
    "bool" : "boolean",
    "c_double" : "double",
    "c_float" : "float",
}

usable_java_type_map = {
    "u8" : "short",
    "i8" : "byte",
    "u16" : "int",
    "i16" : "short",
    "u32" : "long",
    "i32" : "int",
    "c_int" : "int",
    "bool" : "boolean",
    "c_double" : "double",
    "c_float" : "float"
}

pointer_exceptions = {
    "V5_DeviceT" : "V5Device"
}

def usable_java(type, parse_unsigned = True):
    if type["pointer"] == True:
        if pointer_exceptions.get(type["actual"]) is not None:
            return pointer_exceptions[type["actual"]]
        elif all_pointers.get(type["actual"]) == True:
            return type["actual"]
        else:
            return "RawPointer"
    elif (all_enums.get(type["actual"]) is not None):
        return all_enums[type["actual"]]["pretty_name"]
    # elif (all_structs.get(type["actual"]) is not None):
    #     return all_structs[type["actual"]]["pretty_name"]
    else:
        default = usable_java_type_map[type["actual"]]
        if not parse_unsigned and default in ["short", "byte", "long"]:
            default = "int"
        return default

def parse_type(type):
    type_data = {
        "struct": False,
        "enum": False,
        "pointer": False,
    }
    match type:
        case ("i32" | "u32"):
            type_data["wasm"] = type
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 4
        case "c_int": 
            type_data["wasm"] = "i32"
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 4
        case "c_double":
            type_data["wasm"] = type
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 8
        case "c_float":
            type_data["wasm"] = type
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 4
        case "c_char":
            type_data["wasm"] = "i32"
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 1
        case ("u16" | "i16"):
            type_data["wasm"] = "u32"
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 2
        case ("u8" | "i8"):
            type_data["wasm"] = "u32"
            type_data["actual"] = type
            type_data["mutable"] = False
            type_data["size"] = 1
        case "bool":
            type_data["wasm"] = "bool"
            type_data["actual"] = type
            type_data["mutable"] = False
        case x if x[0] == "*":
            match = re.match(r"\*(mut|const) (\w+)", type)
            type_data["wasm"] = "u32"
            type_data["actual"] = match[2]
            type_data["mutable"] = match[1] == "mut"
            type_data["pointer"] = True
        case _:
            if (type == "V5_DeviceT"):
                type_data["wasm"] = "u32"
                type_data["actual"] = type
                type_data["mutable"] = True
                type_data["pointer"] = True
            else:
                is_array = re.match(r"\[\s*(\w+)\s*;\s*(\d+)\s*\]", type);
                if is_array is not None:
                    type_data = parse_type(is_array[1])
                    type_data["array"] = int(is_array[2])
                else:
                    type_data["wasm"] = "u32"
                    type_data["actual"] = type
                    type_data["mutable"] = False
                    type_data["enum"] = True
                    type_data["size"] = 4
    type_data["java"] = java_type_map[type_data["wasm"]]
    return type_data

class EnumException(Exception):
    pass

all_enums = {}
def parse_enum(type, file):
    name = type["actual"]
    if (all_enums.get(name) is not None):
        return all_enums[name]
    if re.search(rf"#\[repr\(transparent\)\](?:\s*#\[.+\])*\s+pub\s+struct\s+{name}\(pub core::ffi::(?:c_uchar|c_uint)\);", file) is None:
        raise EnumException(f"Failed to find declaration for enum {name}!")
    enum_body = re.search(rf"impl\s+{name}\s*{{([^}}]+)}}", file)[1]
    if enum_body is None:
        raise EnumException(f"Failed to find implementation for enum {name}!")
    enum_values = re.findall(r"((?:\s+\/\/\/ ?.*)*)\s+pub\s+const\s+(\w+)\s*:\s+Self\s+=\s+Self(?:::(\w+)|\(((?:0[xX])?\d+)\));", enum_body)
    normed_values = []
    for value in enum_values:
        if (value[3]):
            normed_values.append((value[0], value[1], value[3]))
        else:
            normed_values.append((value[0], value[1], next(v for v in enum_values if v[1] == value[2])[3]))
    all_enums[name] = normed_values
    # type["enum_data"] = normed_values
    return normed_values

class StructException(Exception):
    pass

all_structs = {}
def parse_struct(type, file):
    name = type["actual"]
    if (all_structs.get(name) is not None):
        return all_structs[name]
    struct_body = re.search(rf"#\[repr\(.*(?:C|packed).*\)\](?:\s*#\[.+\])*\s+pub\s+(?:struct|union)\s+{name}\s*{{([^}}]+)}}", file)
    if struct_body is None:
        raise StructException(f"Unable to find struct declaration for {name}!")
    struct_body = struct_body[1]
    struct_values = re.findall(r"pub\s+([\w#]+):\s*([^\n\r,]+)", struct_body)
    struct_values = [(a, parse_type(b)) for (a,b) in struct_values]
    # type["struct_data"] = struct_values
    if next((s for s in struct_values if s[1].get("pointer") == True), None) is not None:
        raise SyntaxError("Unable to parse pointers in structs!")
    for enum in [e for (a,e) in struct_values if e.get("enum") == True]:
        try:
            parse_enum(enum, file)
        except EnumException as e:
            parse_struct(enum, file)
    all_structs[name] = struct_values
    return struct_values
    
all_pointers = {}
def parse_pointer(type, file):
    name = type["actual"]
    if (name in pointer_exceptions):
        return
    if (all_pointers.get(name) is not None):
        type["true_pointer"] = all_pointers[name]
        return type
    # if (parse_type(name).get("enum") == False):
    #     return
    try:
        parse_struct(type, file)
    except StructException as e:
        # print(e)
        pointer_body = re.search(rf"pub\s+type\s+({name})\s*=\s*core::ffi::(?:c_void)", file)
        if pointer_body is not None:
            # raise SyntaxError(f"Unable to find pointer declaration for {name}!")
            type["true_pointer"] = True
        else:
            print(f"Unable to find pointer declaration for {name}!")
            type["true_pointer"] = False
        all_pointers[name] = type["true_pointer"]
    # print(name)
    return type
    

def parse_function(function, file):
    ret = {}
    if (len(function[3]) > 0):
        ret = parse_type(function[3])
    args = re.findall(r"(\w+)\s*:\s*((?:\*\w+\s+)?\w+)\s*(?:,|$)", function[2])
    args = [(a, parse_type(b)) for (a,b) in args]
    enums = [arg for arg in (args + [("|", ret)]) if arg[1].get("enum") == True]
    for enum in enums:
        if (enum[1]["actual"] == "VaList"):
            return (None, None)
        parse_enum(enum[1], file)
    pointers = [arg for arg in (args + [("|", ret)]) if arg[1].get("pointer") == True]
    # print(function[0])
    # print(function[1])
    for pointer in pointers:
       parse_pointer(pointer[1], file)
    return (args, ret)

def parse_doc_comment(comment):
    if (len(comment) < 1):
        return ""
    # print(comment)
    comment = comment.strip()
    comment = re.sub(r"(?m)^.*\/\/\/", "*", comment)
    comment = "/**\n" + comment + "\n*/\n"
    return comment
    

classes = []
all_wasm_bindings = ""

for file in filenames:
    class_name = re.sub(r"(?:^|\_)([a-zA-Z])", lambda i : i.group(1).upper(),re.match(r"^.*?(\w+)\.rs$", file).group(1))
    match(class_name):
        case ("Lib"|"Display"|"Vision"|"Task"|"System"):
            continue
    # print(name)
    contents = open(file).read()
    description = re.match(r"\/\/! ?(.+)", contents)
    if (description is not None):
        description = description[1]
    function_block = re.search(r"map_jump_table\!\s*\{([\s\S]+)\}", contents)
    if (function_block is None):
        raise "Unable to find SDK function macro!"
    functions = re.findall(r"((?:\s+\/\/\/ ?.*)*)\s+pub\s+fn\s+(\w+)\s*\(((?:\s*[\w]+\s*:\s*(?:\*(?:mut|const))?\s+[\w:]+,?)*)\s*\)(?:\s+->\s+([\w\* ]+)(?:,|$))?", function_block.group(1))
    wasm_section = f"// {class_name}\n"
    java_class = f"""@StaticInit
public static final class {class_name} {{
private {class_name}() {{}}
"""
    function_bindings = ""
    function_results = [parse_function(f, contents) for f in functions];
    
    for name in all_enums:
        pretty_name = re.match(rf"(?:V5_?)?(?:Device(?!Type))?(?:{class_name})?(.+)", name)[1]
        name_parts = re.match(r"((?:[A-Z][a-z]*)*)([A-Z][a-z]*)", pretty_name);
        new_data = []
        for value in all_enums[name]:
            pretty_value_name = re.match(rf"(?i)k?(?:V5)?(?:{class_name})?(?:{name_parts[1]}(?:{name_parts[2]})?)?(.+)", value[1])[1]
            pretty_value_name = "_".join(m.upper() for m in re.findall(r"(?:^|\d*[A-Z]+)[^A-Z]*", pretty_value_name) if m)
            new_data.append((value[0], pretty_value_name, value[2]))
        all_enums[name] = {
            "pretty_name": pretty_name,
            "data": new_data
        }
        enum_class = f"""public record {pretty_name}(byte value) {{
""" + "\n".join(f"{parse_doc_comment(v[0])}public static final {pretty_name} {v[1]} = new {pretty_name}((byte) {v[2]});" for v in all_enums[name]["data"]) + f"""
}}"""
        java_class += enum_class
    
    for name in all_structs:
        pretty_name = re.match(rf"(?:V5_?)?(?:Device(?!Type))?(?:{class_name})?(.+)", name)[1]
        data = all_structs[name]
        all_structs[name] = {
            "pretty_name": pretty_name,
            "data": data
        }
    for name in all_structs:
        pretty_name = all_structs[name]["pretty_name"]
        primitives = []
        parameters = []
        data = all_structs[name]["data"]
        currentOffset = 0
        for i, r in enumerate(data):
            if (r[1]["enum"] == True and all_enums.get(r[1]["actual"]) is not None):
                primitives.append("Util.Primitive.i8")
                currentOffset += 1
                r[1]["usable_java"] = all_enums[r[1]["actual"]]["pretty_name"]
                parameters.append(f"new {r[1]["usable_java"]}((byte) values[{i}])")
            elif (r[1]["enum"] == True and all_structs.get(r[1]["actual"]) is not None):
                struct = all_structs[r[1]["actual"]]
                r[1]["usable_java"] = struct["pretty_name"]
                struct_size = sum(v[1]["size"] for v in struct["data"])
                parameters.append(f"{struct["pretty_name"]}.fromByteArray(Arrays.copyOfRange(array, {currentOffset}, {currentOffset + struct_size}))")
                currentOffset += struct_size
            elif r[1]["pointer"] == True:
                raise ValueError("Can't parse pointers in structs!")
            else:
                primitive_type = ""
                if r[1]["actual"] == "c_double":
                    primitive_type = f"Util.Primitive.DOUBLE"
                elif r[1]["actual"] == "c_float":
                    primitive_type = f"Util.Primitive.FLOAT"
                else:
                    primitive_type = f"Util.Primitive.{r[1]["actual"]}"
                if re.search("pad", r[0]) is not None:
                    if r[1].get("array") is not None:
                        new_size = r[1]["size"] * r[1]["array"]
                        currentOffset += new_size
                        match new_size:
                            case 2:
                                primitives.append("Util.Primitive.i16")
                            case 4: 
                                primitives.append("Util.Primitive.i32")
                            case _:
                                raise ValueError(f"Invalid array size for struct! ({new_size}, {r[0]}, {r[1]["actual"]})")
                    else:
                        primitives.append(primitive_type)
                        currentOffset += r[1]["size"]
                    r[1]["pad"] = True
                elif r[1].get("array") is not None:
                    raise ValueError("Unable to parse arrays in structs!")
                else:         
                    r[1]["usable_java"] = usable_java_type_map[r[1]["actual"]]
                    primitives.append(primitive_type)
                    parameters.append(f"({r[1]["usable_java"]}) values[{i}]")
                    currentOffset += r[1]["size"]
        struct_class = f"public record {pretty_name}(\n" + ",\n".join([f"{r[1]["usable_java"]} {r[0]}" for r in data if r[1].get("pad") != True]) + "\n) {\n"
        struct_class += f"public static final int SIZE = {currentOffset};"
        struct_class += f"""public static {pretty_name} fromByteArray(byte[] array) {{
var values = Util.parseStruct(array, new Util.Primitive[]{{
{",\n".join(primitives)}
}});
return new {pretty_name}({", ".join(parameters)});
}}
}}"""
        java_class += struct_class
    
    for f, results in zip(functions, function_results):
        if (results[0] is None):
            continue
        # Create wasm bindings
        def wrap_param(type):
            if (type["enum"] == True):
                return " as " + type["actual"]
            else:
                return ""
        wasm_binding = f"fn {f[1]}({", ".join(f"{r[0]}: {r[1]["wasm"]}{wrap_param(r[1])}" for r in results[0])})"
        if (results[1].get("wasm") is not None):
            wasm_binding = wasm_binding + f" -> {results[1]["wasm"]}"
            if (results[1].get("enum") == True):
                wasm_binding += ", in .0"
        wasm_binding += ";"
        wasm_section += wasm_binding + "\n"
        # Create java bindings
        java_binding = f"""@Import(module = "vex", name = "{f[1]}")
private static native {"void" if (results[1].get("java") is None) else results[1]["java"]} _{f[1]}({", ".join(f"{r[1]["java"]} {r[0]}" for r in results[0])});
"""
        getset = re.match(r"(.+)(Get|Set)$", f[1])
        pretty_name = re.match(rf"(?:vex)?(?:Device(?!s))?(?:{class_name}(?![a-z]))?(.+)", getset[1] if (getset is not None) else f[1])[1]
        pretty_name = pretty_name[0].lower() + pretty_name[1:]
        if getset is not None:
            pretty_name = getset[2][0].lower() + getset[2][1:] + pretty_name[0].upper() + pretty_name[1:]
        def convert(name, type):
            if type["enum"] == True:
                return name + ".value"
            elif type["pointer"] == True:
                return name + ".raw"
            else:
                match (type["actual"]):
                    # case "bool":
                    #     return name + " ? 1 : 0"
                    case ("u8"|"i8"|"u16"|"i16"|"i32"|"u32"):
                        return "(int)" + name
                    case _:
                        return name
        ugly_call = f"_{f[1]}({", ".join(convert(r[0], r[1]) for r in results[0])})"
        function_body = ugly_call + ";"
        if (results[1]):
            function_body = "var result = " + ugly_call + ";\nreturn "
            if results[1]["enum"] == True:
                function_body += f"new {all_enums[results[1]["actual"]]["pretty_name"]}((byte) result)"
            elif results[1]["pointer"] == True:
                function_body += f"new {usable_java(results[1])}(result)"
            elif results[1]["struct"] == True:
                raise ValueError("Unable to parse struct by value!")
            # elif results[1]["actual"] == "bool":
            #     function_body += "result != 0"
            elif results[1]["java"] in ["int","double","float","boolean"]:
                function_body = "return " + ugly_call
            else:
                raise ValueError(f"can't parse whatever {results[1]["actual"]} is")
            function_body += ";"
        java_pretty = parse_doc_comment(f[0]) + f"""public static {"void" if (results[1].get("java") is None) else usable_java(results[1], False)} {pretty_name}({", ".join(f"{usable_java(r[1])} {r[0]}" for r in results[0])}) {{
    {function_body}
}}
"""
        function_bindings += java_binding
        function_bindings += java_pretty
    
    all_structs.clear()
    all_enums.clear()
    java_class += function_bindings
    java_class += "}"
    classes.append(java_class)
    all_wasm_bindings += wasm_section

    # print(enum_class)

# print(all_pointers);
# print([[v[1]["actual"] for v in all_structs[s]] for s in all_structs]);
        
    # print(all_enums[name]);
# print(all_wasm_bindings)
# print("\n".join(classes))
os.makedirs('hydrozoa/java/sdk', exist_ok=True)
java_output = open("hydrozoa/java/sdk/VexSdk.java", "w")
java_output.write("""package dev.vexide.hydrozoa.sdk;

import org.teavm.interop.Import;
import org.teavm.interop.StaticInit;
import dev.vexide.hydrozoa.sdk.Hydrozoa.Util;
import java.util.Arrays;

@SuppressWarnings("MissingJavadoc")
@StaticInit
public final class VexSdk {
    private VexSdk() {
    }
    
    public record RawPointer(int raw){}
""" + "\n".join(f"public record {r}(int raw){{}}" for r in pointer_exceptions.values()) + "\n".join(f"public record {r}(int raw){{}}" for r in all_pointers if all_pointers[r] == True) + "\n".join(classes) + "\n}")
java_output.close()

wasm_output = open("hydrozoa/wasm.txt", "w")
wasm_output.write(all_wasm_bindings)
wasm_output.close()