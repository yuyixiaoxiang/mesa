# encoding=utf-8
# Copyright © 2017 Intel Corporation

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Create enum to string functions for vulkan using vk.xml."""

from __future__ import print_function
import argparse
import os
import textwrap
import xml.etree.cElementTree as et

from mako.template import Template

COPYRIGHT = textwrap.dedent(u"""\
    * Copyright © 2017 Intel Corporation
    *
    * Permission is hereby granted, free of charge, to any person obtaining a copy
    * of this software and associated documentation files (the "Software"), to deal
    * in the Software without restriction, including without limitation the rights
    * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    * copies of the Software, and to permit persons to whom the Software is
    * furnished to do so, subject to the following conditions:
    *
    * The above copyright notice and this permission notice shall be included in
    * all copies or substantial portions of the Software.
    *
    * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    * SOFTWARE.""")

C_TEMPLATE = Template(textwrap.dedent(u"""\
    /* Autogenerated file -- do not edit
     * generated by ${file}
     *
     ${copyright}
     */

    #include <vulkan/vulkan.h>
    #include <vulkan/vk_android_native_buffer.h>
    #include "util/macros.h"
    #include "vk_enum_to_str.h"

    % for enum in enums:

    const char *
    vk_${enum.name[2:]}_to_str(${enum.name} input)
    {
        switch(input) {
        % for v in sorted(enum.values.keys()):
            % if enum.values[v] in FOREIGN_ENUM_VALUES:

            #pragma GCC diagnostic push
            #pragma GCC diagnostic ignored "-Wswitch"
            % endif
            case ${v}:
                return "${enum.values[v]}";
            % if enum.values[v] in FOREIGN_ENUM_VALUES:
            #pragma GCC diagnostic pop

            % endif
        % endfor
        default:
            unreachable("Undefined enum value.");
        }
    }
    %endfor"""),
    output_encoding='utf-8')

H_TEMPLATE = Template(textwrap.dedent(u"""\
    /* Autogenerated file -- do not edit
     * generated by ${file}
     *
     ${copyright}
     */

    #ifndef MESA_VK_ENUM_TO_STR_H
    #define MESA_VK_ENUM_TO_STR_H

    #include <vulkan/vulkan.h>
    #include <vulkan/vk_android_native_buffer.h>

    #ifdef __cplusplus
    extern "C" {
    #endif

    % for ext in extensions:
    #define _${ext.name}_number (${ext.number})
    % endfor

    % for enum in enums:
    const char * vk_${enum.name[2:]}_to_str(${enum.name} input);
    % endfor

    #ifdef __cplusplus
    } /* extern "C" */
    #endif

    #endif"""),
    output_encoding='utf-8')

# These enums are defined outside their respective enum blocks, and thus cause
# -Wswitch warnings.
FOREIGN_ENUM_VALUES = [
    "VK_STRUCTURE_TYPE_NATIVE_BUFFER_ANDROID",
]


class NamedFactory(object):
    """Factory for creating enums."""

    def __init__(self, type_):
        self.registry = {}
        self.type = type_

    def __call__(self, name, **kwargs):
        try:
            return self.registry[name]
        except KeyError:
            n = self.registry[name] = self.type(name, **kwargs)
        return n

    def get(self, name):
        return self.registry.get(name)


class VkExtension(object):
    """Simple struct-like class representing extensions"""

    def __init__(self, name, number=None):
        self.name = name
        self.number = number


class VkEnum(object):
    """Simple struct-like class representing a single Vulkan Enum."""

    def __init__(self, name, values=None):
        self.name = name
        # Maps numbers to names
        self.values = values or dict()
        self.name_to_value = dict()

    def add_value(self, name, value=None,
                  extnum=None, offset=None,
                  error=False):
        assert value is not None or extnum is not None
        if value is None:
            value = 1000000000 + (extnum - 1) * 1000 + offset
            if error:
                value = -value

        self.name_to_value[name] = value
        if value not in self.values:
            self.values[value] = name
        elif len(self.values[value]) > len(name):
            self.values[value] = name

    def add_value_from_xml(self, elem, extension=None):
        if 'value' in elem.attrib:
            self.add_value(elem.attrib['name'],
                           value=int(elem.attrib['value'], base=0))
        elif 'alias' in elem.attrib:
            self.add_value(elem.attrib['name'],
                           value=self.name_to_value[elem.attrib['alias']])
        else:
            error = 'dir' in elem.attrib and elem.attrib['dir'] == '-'
            if 'extnumber' in elem.attrib:
                extnum = int(elem.attrib['extnumber'])
            else:
                extnum = extension.number
            self.add_value(elem.attrib['name'],
                           extnum=extnum,
                           offset=int(elem.attrib['offset']),
                           error=error)


def parse_xml(enum_factory, ext_factory, filename):
    """Parse the XML file. Accumulate results into the factories.

    This parser is a memory efficient iterative XML parser that returns a list
    of VkEnum objects.
    """

    xml = et.parse(filename)

    for enum_type in xml.findall('./enums[@type="enum"]'):
        enum = enum_factory(enum_type.attrib['name'])
        for value in enum_type.findall('./enum'):
            enum.add_value_from_xml(value)

    for value in xml.findall('./feature/require/enum[@extends]'):
        enum = enum_factory.get(value.attrib['extends'])
        if enum is not None:
            enum.add_value_from_xml(value)

    for ext_elem in xml.findall('./extensions/extension[@supported="vulkan"]'):
        extension = ext_factory(ext_elem.attrib['name'],
                                number=int(ext_elem.attrib['number']))

        for value in ext_elem.findall('./require/enum[@extends]'):
            enum = enum_factory.get(value.attrib['extends'])
            if enum is not None:
                enum.add_value_from_xml(value, extension)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--xml', required=True,
                        help='Vulkan API XML files',
                        action='append',
                        dest='xml_files')
    parser.add_argument('--outdir',
                        help='Directory to put the generated files in',
                        required=True)

    args = parser.parse_args()

    enum_factory = NamedFactory(VkEnum)
    ext_factory = NamedFactory(VkExtension)
    for filename in args.xml_files:
        parse_xml(enum_factory, ext_factory, filename)
    enums = sorted(enum_factory.registry.values(), key=lambda e: e.name)
    extensions = sorted(ext_factory.registry.values(), key=lambda e: e.name)

    for template, file_ in [(C_TEMPLATE, os.path.join(args.outdir, 'vk_enum_to_str.c')),
                            (H_TEMPLATE, os.path.join(args.outdir, 'vk_enum_to_str.h'))]:
        with open(file_, 'wb') as f:
            f.write(template.render(
                file=os.path.basename(__file__),
                enums=enums,
                extensions=extensions,
                copyright=COPYRIGHT,
                FOREIGN_ENUM_VALUES=FOREIGN_ENUM_VALUES))


if __name__ == '__main__':
    main()
