import java.nio.file.*;
import java.util.zip.*;
import org.objectweb.asm.*;

/** Add a timeout to the two HTTP request builders without changing mod content. */
public class AddCosmeticsTimeout {
    public static void main(String[] args) throws Exception {
        int[] changes = {0};
        try (ZipFile input = new ZipFile(args[0]);
             ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(Path.of(args[1])))) {
            var entries = input.entries();
            while (entries.hasMoreElements()) {
                var entry = entries.nextElement();
                byte[] bytes = input.getInputStream(entry).readAllBytes();
                if (entry.getName().equals("com/teamresourceful/resourcefulcosmetics/CosmeticsHttp.class")) {
                    var reader = new ClassReader(bytes);
                    var writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
                    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
                        @Override public MethodVisitor visitMethod(int access, String name, String desc, String signature, String[] exceptions) {
                            return new MethodVisitor(Opcodes.ASM9, super.visitMethod(access, name, desc, signature, exceptions)) {
                                @Override public void visitMethodInsn(int opcode, String owner, String method, String descriptor, boolean isInterface) {
                                    super.visitMethodInsn(opcode, owner, method, descriptor, isInterface);
                                    if (owner.equals("java/net/http/HttpRequest") && method.equals("newBuilder") && descriptor.equals("()Ljava/net/http/HttpRequest$Builder;")) {
                                        super.visitLdcInsn(8L);
                                        super.visitMethodInsn(Opcodes.INVOKESTATIC, "java/time/Duration", "ofSeconds", "(J)Ljava/time/Duration;", false);
                                        super.visitMethodInsn(Opcodes.INVOKEINTERFACE, "java/net/http/HttpRequest$Builder", "timeout", "(Ljava/time/Duration;)Ljava/net/http/HttpRequest$Builder;", true);
                                        changes[0]++;
                                    }
                                }
                            };
                        }
                    }, 0);
                    bytes = writer.toByteArray();
                }
                output.putNextEntry(new ZipEntry(entry.getName()));
                output.write(bytes);
                output.closeEntry();
            }
        }
        if (changes[0] != 2) throw new IllegalStateException("Expected two HTTP builders, got " + changes[0]);
        System.out.println("Added 8-second timeout to " + changes[0] + " HTTP builders.");
    }
}
